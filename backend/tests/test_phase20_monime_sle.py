"""Monime connection robustness, the return from the payment page, and SLE as the only currency."""
import io
import urllib.error

import pytest
from rest_framework.test import APIClient

from apps.payments import providers

from .test_phase5_orders import checkout, clean, line, shop  # noqa: F401


class Reply:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return io.BytesIO(self.body)

    def __exit__(self, *a):
        return False


@pytest.fixture
def monime(settings, monkeypatch):
    from django.core.cache import cache

    cache.clear()
    settings.MONIME_ACCESS_TOKEN, settings.MONIME_SPACE_ID, settings.MONIME_WEBHOOK_SECRET = "mon_test_x", "spc-x", "w" * 40
    monkeypatch.setattr(providers.MonimeProvider, "RETRY_WAIT", 0)
    return providers.MonimeProvider()


def gateway_error(code=503):
    return urllib.error.HTTPError("https://api.monime.io", code, "x", {}, io.BytesIO(b'{"error":{"message":"no healthy upstream"}}'))


def serve(monkeypatch, handler):
    monkeypatch.setattr(providers.urllib.request, "urlopen", handler)


def route(monkeypatch, handlers, log):
    """handlers: {(method, path prefix): callable() -> Reply | raises}."""

    def urlopen(req, timeout):
        method, path = req.get_method(), req.full_url.split("/v1", 1)[1]
        log.append((method, path, req.get_header("Idempotency-key"), timeout))
        for (m, prefix), handler in handlers.items():
            if method == m and path.startswith(prefix):
                return handler()
        raise AssertionError((method, path))

    serve(monkeypatch, urlopen)


def reply(body):
    return lambda: Reply(body)


def fail(code):
    def handler():
        raise gateway_error(code)

    return handler


SESSION = b'{"success":true,"result":{"id":"sps-1","redirectUrl":"https://pay.monime.io/s/1"}}'
CODE = b'{"success":true,"result":{"id":"pmc-1","status":"pending","ussdCode":"*715*123456#","amount":{"currency":"SLE","value":1250}}}'


def create(monime, reference="PAY-1"):
    return monime.create_payment(reference=reference, amount="12.50", currency="SLE", phone="", return_url="https://x/ok", cancel_url="https://x/no")


def test_the_hosted_payment_page_is_used_when_it_works(monime, monkeypatch):
    calls = []
    route(monkeypatch, {("POST", "/checkout-sessions"): reply(SESSION)}, calls)
    made = create(monime)
    assert made.redirect_url == "https://pay.monime.io/s/1" and not made.ussd_code and len(calls) == 1


def test_when_the_checkout_service_fails_a_dial_code_is_offered_and_nobody_waits_for_it_again(monime, monkeypatch):
    calls = []
    route(monkeypatch, {("POST", "/checkout-sessions"): fail(500), ("POST", "/payment-codes"): reply(CODE)}, calls)
    made = create(monime)
    assert made.provider_ref == "pmc-1" and made.ussd_code == "*715*123456#" and not made.redirect_url
    assert [c[1] for c in calls] == ["/checkout-sessions", "/payment-codes"] and calls[0][3] == monime.CHECKOUT_TIMEOUT
    assert calls[1][2] == "PAY-1-code"
    calls.clear()
    create(monime, "PAY-2")
    assert [c[1] for c in calls] == ["/payment-codes"]  # the broken service is skipped for a few minutes


def test_a_brief_outage_is_retried_with_the_same_idempotency_key(monime, monkeypatch):
    calls, tries = [], []

    def flaky():
        tries.append(1)
        if len(tries) < 3:
            raise gateway_error(503)
        return Reply(CODE)

    route(monkeypatch, {("POST", "/checkout-sessions"): fail(500), ("POST", "/payment-codes"): flaky}, calls)
    assert create(monime).provider_ref == "pmc-1"
    assert [c[2] for c in calls if c[1] == "/payment-codes"] == ["PAY-1-code"] * 3


def test_refusals_are_not_retried_and_a_lasting_outage_gives_up(monime, monkeypatch):
    calls = []
    route(monkeypatch, {("POST", "/checkout-sessions"): fail(403), ("POST", "/payment-codes"): fail(403)}, calls)
    with pytest.raises(providers.ProviderError, match="403"):
        create(monime)
    assert len(calls) == 2  # one try each
    calls.clear()
    route(monkeypatch, {("GET", "/payment-codes/"): fail(503)}, calls)
    with pytest.raises(providers.ProviderError, match="503"):
        monime.fetch_status("pmc-1")
    assert len(calls) == 3


@pytest.mark.parametrize("remote,ours", [("pending", "pending"), ("processing", "pending"), ("completed", "succeeded"), ("expired", "failed"), ("cancelled", "failed")])
def test_dial_code_status_mapping(monime, monkeypatch, remote, ours):
    body = b'{"success":true,"result":{"status":"' + remote.encode() + b'","amount":{"currency":"SLE","value":1250}}}'
    route(monkeypatch, {("GET", "/payment-codes/pmc-1"): reply(body)}, [])
    status = monime.fetch_status("pmc-1")
    assert (status.status, str(status.amount), status.currency) == (ours, "12.50", "SLE")


def test_payment_code_webhooks_are_recognised(monime):
    event = monime.parse_event({"event": {"id": "wke-1", "name": "payment_code.completed"}, "object": {"id": "pmc-1"}})
    assert event.provider_ref == "pmc-1"
    with pytest.raises(providers.IgnoredEvent):
        monime.parse_event({"event": {"id": "wke-2", "name": "payout.completed"}, "object": {"id": "x"}})


def test_customer_pays_by_dial_code_and_the_order_is_confirmed_only_after_monime_says_so(world, shop, clean, monime, monkeypatch, settings):  # noqa: F811
    from apps.orders.models import Order
    from apps.tenants.models import RestaurantSettings

    from .conftest import client_for

    settings.PAYMENT_PROVIDER = "monime"
    RestaurantSettings.objects.filter(restaurant=world["a"]).update(online_payments_enabled=True)
    state = {"status": "pending", "value": 0}

    def create_code():
        return Reply(('{"success":true,"result":{"id":"pmc-9","ussdCode":"*715*999#","status":"pending"}}').encode())

    def read_code():
        return Reply(('{"success":true,"result":{"status":"%s","amount":{"currency":"SLE","value":%d}}}' % (state["status"], state["value"])).encode())

    route(monkeypatch, {("POST", "/checkout-sessions"): fail(500), ("POST", "/payment-codes"): create_code, ("GET", "/payment-codes/pmc-9"): read_code}, [])
    c = client_for(world["cust_a"], "alpha")
    order = checkout(world, [line(shop["rice"], 1)], key="ussd-1", payment_method="mobile_money").data
    started = c.post("/api/v1/payments/initiate/", {"order_id": order["id"], "phone": "+23276123456"}, format="json", HTTP_IDEMPOTENCY_KEY="ussd-init")
    assert started.status_code == 201, started.content
    pay = started.data
    assert pay["ussd_code"] == "*715*999#" and pay["redirect_url"] == "" and pay["status"] == "pending"
    assert c.get(f"/api/v1/orders/my/{order['id']}/").data["payments"][0]["ussd_code"] == "*715*999#"
    assert c.get(f"/api/v1/payments/my/{pay['id']}/").data["status"] == "pending"
    assert Order.unscoped.get(pk=order["id"]).payment_status == "unpaid"
    state.update(status="completed", value=int(Order.unscoped.get(pk=order["id"]).total * 100))
    done = c.get(f"/api/v1/payments/my/{pay['id']}/").data
    assert done["status"] == "succeeded" and done["ussd_code"] == ""
    paid = Order.unscoped.get(pk=order["id"])
    assert paid.payment_status == "paid" and paid.status == "confirmed"


def test_only_sle_is_sent_and_both_item_list_shapes_are_read(monime, monkeypatch):
    with pytest.raises(providers.ProviderError, match="SLE"):
        monime.create_payment(reference="P", amount="1.00", currency="USD", phone="", return_url="https://x/y")
    wrapped = b'{"data":[{"quantity":2,"price":{"currency":"SLE","value":1250}}]}'
    bare = b'[{"quantity":2,"price":{"currency":"SLE","value":"1250"}}]'
    for items in (wrapped, bare):
        serve(monkeypatch, lambda req, timeout, items=items: Reply(b'{"success":true,"result":{"status":"completed","lineItems":' + items + b"}}"))
        status = monime.fetch_status("sps-1")
        assert (status.status, str(status.amount), status.currency) == ("succeeded", "25.00", "SLE")


def test_returning_from_the_payment_page_by_post_lands_on_the_page(world, settings, tmp_path):
    (tmp_path / "i.html").write_text('<html><head><title>x</title><!--runtime-config--></head><body><div id="root"></div></body></html>')
    settings.SPA_INDEX = tmp_path / "i.html"
    c = APIClient(HTTP_HOST="platform.test", enforce_csrf_checks=True)
    r = c.post("/alpha/account/orders/7?x=1", {"anything": "1"})
    assert r.status_code == 303 and r["Location"] == "/alpha/account/orders/7?x=1"
    hostile = c.post("//evil.example.com/path")
    assert not hostile.get("Location", "/").startswith("//")


# ------------------------------------------------------------------ SLE only
def test_currency_is_sle_everywhere_and_cannot_be_changed(world, db):
    from apps.tenants.models import Restaurant, SubscriptionPlan

    from .conftest import client_for

    assert Restaurant.objects.create(name="N", slug="newplace").get_settings().currency == "SLE"
    root = client_for(world["platform"])
    r = root.post("/api/v1/platform/plans/", {"name": "Pro", "slug": "pro", "price": "10.00", "currency": "USD", "features": []}, format="json")
    assert r.status_code == 201, r.content
    assert SubscriptionPlan.objects.get(slug="pro").currency == "SLE"


# ------------------------------------------------------------------ 80 mm receipt
from .test_phase6_payments import cash, place  # noqa: E402


def test_receipt_pdf_is_an_80mm_roll_carrying_the_restaurants_details(world, shop):  # noqa: F811
    import re

    from .conftest import client_for

    a = world["a"]
    a.address, a.city, a.contact_phone, a.contact_email = "1 Beach Road", "Freetown", "+23276000000", "hello@alpha.test"
    a.save()
    st = a.get_settings()
    st.receipt_footer = "See you again at Alpha!"
    st.save()
    order = place(world, shop, method="cash")
    rid = cash(world, "cashier_a1", order["id"], "20.00").data["receipt_id"]
    c = client_for(world["cashier_a1"], "alpha")
    d = c.get(f"/api/v1/payments/receipts/{rid}/").data
    assert d["footer"] == "See you again at Alpha!" and d["website"].endswith("/alpha") and d["qr"].startswith("data:image/png;base64,")
    assert d["currency"] == "SLE" and d["restaurant"]["city"] == "Freetown"
    pdf = c.get(f"/api/v1/payments/receipts/{rid}/pdf/").content
    box = [float(x) for x in re.search(rb"/MediaBox \[\s*([\d. ]+)\]", pdf).group(1).split()]
    assert abs((box[2] - box[0]) * 25.4 / 72 - 80) < 0.1  # exactly 80 mm wide
    assert 100 < (box[3] - box[1]) * 25.4 / 72 < 300      # as long as its content, one page
    assert pdf.count(b"/Type /Page\n") <= 1


def test_very_long_names_still_fit_on_the_roll():
    from apps.payments.receipt_pdf import render_pdf

    data = {"number": "RCT-1", "order_number": "ORD-1", "currency": "SLE", "fulfilment": "dine_in", "cashier": "A" * 150,
            "restaurant": {"name": "The Extremely Long Named Restaurant and Grill House of Freetown " * 2, "phone": "", "email": "", "address": "x" * 200, "city": ""},
            "branch": {"name": "Main", "address": "", "phone": ""}, "customer": {"name": "Nǃaïve ☕ Customer"},
            "items": [{"name": "Supercalifragilisticexpialidocious" * 3, "variation": "", "quantity": 2, "unit_price": "1000000.00", "line_total": "2000000.00", "addons": []}],
            "totals": {"subtotal": "2000000.00", "discount": "0", "tax": "0", "delivery_fee": "0", "total": "2000000.00"},
            "payment": {"method": "cash", "reference": "PAY-1", "amount": "2000000.00", "received": "", "change": "0", "paid_at": "2026-11-26T10:00:00+00:00"},
            "website": "https://ntsrestaurant.onrender.com/a-restaurant", "footer": ""}
    assert render_pdf(data).startswith(b"%PDF")
