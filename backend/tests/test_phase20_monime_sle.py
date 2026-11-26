"""Monime connection robustness, the return from the payment page, and SLE as the only currency."""
import io
import urllib.error

import pytest
from rest_framework.test import APIClient

from apps.payments import providers


class Reply:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return io.BytesIO(self.body)

    def __exit__(self, *a):
        return False


@pytest.fixture
def monime(settings, monkeypatch):
    settings.MONIME_ACCESS_TOKEN, settings.MONIME_SPACE_ID, settings.MONIME_WEBHOOK_SECRET = "mon_test_x", "spc-x", "w" * 40
    monkeypatch.setattr(providers.MonimeProvider, "RETRY_WAIT", 0)
    return providers.MonimeProvider()


def gateway_error(code=503):
    return urllib.error.HTTPError("https://api.monime.io", code, "x", {}, io.BytesIO(b'{"error":{"message":"no healthy upstream"}}'))


def serve(monkeypatch, handler):
    monkeypatch.setattr(providers.urllib.request, "urlopen", handler)


def test_a_brief_outage_is_retried_with_the_same_idempotency_key(monime, monkeypatch):
    seen = []

    def urlopen(req, timeout):
        seen.append((req.get_header("Authorization"), req.get_header("Idempotency-key")))
        if len(seen) < 3:
            raise gateway_error()
        return Reply(b'{"success":true,"result":{"id":"sps-1","redirectUrl":"https://pay.monime.io/s/1"}}')

    serve(monkeypatch, urlopen)
    made = monime.create_payment(reference="PAY-1", amount="12.50", currency="SLE", phone="", return_url="https://x/y")
    assert made.provider_ref == "sps-1" and len(seen) == 3
    assert {s[1] for s in seen} == {"PAY-1"} and seen[0][0] == "Bearer mon_test_x"


def test_refusals_are_not_retried_and_a_lasting_outage_gives_up(monime, monkeypatch):
    calls = []

    def fail_with(code):
        def urlopen(req, timeout):
            calls.append(1)
            raise gateway_error(code)

        return urlopen

    serve(monkeypatch, fail_with(403))
    with pytest.raises(providers.ProviderError, match="403"):
        monime.create_payment(reference="PAY-2", amount="1.00", currency="SLE", phone="", return_url="https://x/y")
    assert len(calls) == 1
    calls.clear()
    serve(monkeypatch, fail_with(503))
    with pytest.raises(providers.ProviderError, match="503"):
        monime.fetch_status("sps-1")
    assert len(calls) == 3


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
from .test_phase5_orders import clean, shop  # noqa: E402,F401
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
