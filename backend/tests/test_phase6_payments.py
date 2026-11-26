import json
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.db import IntegrityError, transaction
from tests.conftest import TenantClient as APIClient

from apps.core.models import AuditLog
from apps.notifications.providers import ConsoleProvider
from apps.orders.models import Order, Status
from apps.payments import services
from apps.payments.models import Payment, PaymentEvent, Receipt
from apps.payments.providers import ProviderError, SimulatedProvider, get_provider

from .conftest import client_for, host
from .test_phase5_orders import clean, line, shop  # noqa: F401  (fixtures)

P = "/api/v1/payments/"
O = "/api/v1/orders/"
SIM = SimulatedProvider()


@pytest.fixture
def online(shop):
    shop["settings"].online_payments_enabled = True
    shop["settings"].save()
    return shop


def place(world, shop, method="mobile_money", who="cust_a", key=None, qty=1, branch="a1"):
    c = client_for(world[who], "alpha")
    body = {"items": [line(shop["rice"], qty)], "fulfilment": "pickup", "payment_method": method,
            "contact_phone": "+23276123456", "branch_id": world[branch].pk}
    r = c.post(O + "checkout/", body, format="json", HTTP_IDEMPOTENCY_KEY=key or f"co-{Order.unscoped.count()}-{who}")
    assert r.status_code == 201, r.data
    return r.data


def initiate(world, order_id, key="init-1", who="cust_a", phone="+23276123456"):
    return client_for(world[who], "alpha").post(P + "initiate/", {"order_id": order_id, "phone": phone}, format="json", HTTP_IDEMPOTENCY_KEY=key)


def webhook(ref, event_id="evt-1", sign=True, body=None, provider="simulated", signature=None):
    raw = json.dumps(body or {"id": event_id, "type": "payment.succeeded", "data": {"provider_ref": ref}}).encode()
    headers = {"HTTP_X_SIGNATURE": signature if signature is not None else SIM.sign(raw)} if sign else {}
    return APIClient(HTTP_HOST=host()).post(f"{P}webhooks/{provider}/", data=raw, content_type="application/json", **headers)


def paid_order(world, online, outcome="succeeded"):
    order = place(world, online)
    pay = initiate(world, order["id"]).data
    ref = Payment.unscoped.get(pk=pay["id"]).provider_ref
    SIM.set_outcome(ref, outcome)
    return order, Payment.unscoped.get(pk=pay["id"]), ref


# ---- enabling online payment -------------------------------------------------------------------
def test_mobile_money_checkout_needs_the_restaurant_to_enable_it(world, shop):
    shop["settings"].online_payments_enabled = False
    shop["settings"].save()
    c = client_for(world["cust_a"], "alpha")
    body = {"items": [line(shop["rice"])], "fulfilment": "pickup", "payment_method": "mobile_money", "contact_phone": "+23276123456", "branch_id": world["a1"].pk}
    assert c.post(O + "checkout/", body, format="json", HTTP_IDEMPOTENCY_KEY="a").status_code == 400
    shop["settings"].online_payments_enabled = True
    shop["settings"].save()
    assert c.post(O + "checkout/", body, format="json", HTTP_IDEMPOTENCY_KEY="a").status_code == 201


def test_simulated_provider_is_refused_outside_development(settings):
    settings.DEBUG, settings.TESTING_PAYMENTS = False, False
    with pytest.raises(ProviderError):
        get_provider("simulated")
    settings.PAYMENT_PROVIDER = "monime"
    settings.MONIME_API_KEY = settings.MONIME_BASE_URL = settings.MONIME_WEBHOOK_SECRET = ""
    from apps.payments.providers import online_payments_available
    assert online_payments_available() is False  # unconfigured provider is never offered


# ---- initiation --------------------------------------------------------------------------------
def test_initiate_creates_one_pending_payment_and_moves_order_to_processing(world, online):
    order = place(world, online)
    r = initiate(world, order["id"])
    assert r.status_code == 201 and r.data["status"] == "pending" and r.data["amount"] == order["total"]
    o = Order.unscoped.get(pk=order["id"])
    assert o.status == Status.PAYMENT_PROCESSING and o.payment_status == "unpaid"
    assert initiate(world, order["id"]).status_code == 201 and Payment.unscoped.count() == 1  # replay of the same key
    again = initiate(world, order["id"], key="init-2")
    assert again.data["id"] == r.data["id"] and Payment.unscoped.count() == 1  # a second click never starts a second charge


def test_only_one_pending_online_payment_per_order_at_database_level(world, online):
    order = place(world, online)
    p = Payment.unscoped.get(pk=initiate(world, order["id"]).data["id"])
    with pytest.raises(IntegrityError), transaction.atomic():
        Payment.unscoped.create(restaurant=p.restaurant, branch=p.branch, order=p.order, reference="X-2", provider="simulated",
                                method="mobile_money", amount=p.amount, currency=p.currency, provider_ref="SIM-other")


def test_initiate_rules(world, online):
    mine, other = place(world, online), place(world, online, who="cust2_a")
    assert initiate(world, other["id"]).status_code == 400  # someone else's order
    assert initiate(world, mine["id"], phone="abc").status_code == 400
    assert client_for(world["cust_a"], "alpha").post(P + "initiate/", {"order_id": mine["id"], "phone": "+23276"}, format="json").status_code == 400  # no key
    cash = place(world, online, method="cash")
    assert initiate(world, cash["id"], key="c").status_code == 400
    for who in ("admin_a", "cashier_a1"):
        assert client_for(world[who], "alpha").post(P + "initiate/", {"order_id": mine["id"], "phone": "+23276123"}, format="json", HTTP_IDEMPOTENCY_KEY="s").status_code == 403
    assert APIClient(HTTP_HOST=host("alpha")).post(P + "initiate/", {}, format="json").status_code == 401


def test_provider_outage_leaves_order_unpaid_and_retryable(world, online, monkeypatch):
    order = place(world, online)

    def boom(self, **kw):
        raise ProviderError("down")

    monkeypatch.setattr(SimulatedProvider, "create_payment", boom)
    r = initiate(world, order["id"], key="x")
    assert r.status_code == 400 and "unavailable" in json.dumps(r.data)
    assert Payment.unscoped.count() == 0 and Order.unscoped.get(pk=order["id"]).status == Status.AWAITING_PAYMENT
    monkeypatch.undo()
    assert initiate(world, order["id"], key="y").status_code == 201


# ---- webhooks ----------------------------------------------------------------------------------
def test_signed_webhook_settles_payment_confirms_order_and_issues_one_receipt(world, online):
    order, pay, ref = paid_order(world, online)
    r = webhook(ref)
    assert r.status_code == 200 and r.data["data"]["processed"] is True
    pay.refresh_from_db()
    o = Order.unscoped.get(pk=order["id"])
    assert pay.status == "succeeded" and pay.paid_at and o.status == Status.CONFIRMED
    assert (o.amount_paid, o.payment_status) == (o.total, "paid")
    rc = Receipt.unscoped.get()
    assert rc.number == "RCT-000001" and rc.data["payment"]["reference"] == pay.reference and rc.data["totals"]["total"] == str(o.total)
    mails = [m for m in ConsoleProvider.outbox if "RCT-000001" in m["html"]]
    assert len(mails) == 1 and mails[0]["to"] == "cust@a.com"
    assert AuditLog.objects.filter(action="payment.succeeded").count() == 1
    assert [h.to_status for h in o.history.all()][-2:] == ["payment_processing", "confirmed"]


def test_replayed_webhook_creates_no_duplicates(world, online):
    order, pay, ref = paid_order(world, online)
    assert webhook(ref, "evt-A").status_code == 200
    second = webhook(ref, "evt-A")
    assert second.status_code == 200 and second.data["data"] == {"duplicate": True}
    assert webhook(ref, "evt-B").status_code == 200  # a different event id for an already-settled payment
    assert Payment.unscoped.count() == 1 and Receipt.unscoped.count() == 1 and PaymentEvent.objects.count() == 2
    assert Order.unscoped.get(pk=order["id"]).amount_paid == Decimal(order["total"])
    assert len([m for m in ConsoleProvider.outbox if "RCT-000001" in m["html"]]) == 1


def test_forged_or_unsigned_webhooks_are_rejected_and_change_nothing(world, online):
    order, pay, ref = paid_order(world, online)
    assert webhook(ref, sign=False).status_code == 401
    assert webhook(ref, signature="deadbeef").status_code == 401
    assert webhook(ref, signature="").status_code == 401
    assert webhook("nope", provider="monime").status_code in (401, 404)
    assert webhook(ref, provider="bogus").status_code == 404
    pay.refresh_from_db()
    assert pay.status == "pending" and PaymentEvent.objects.count() == 0 and Receipt.unscoped.count() == 0
    assert AuditLog.objects.filter(action="payment.webhook_rejected").count() >= 3


def test_a_correctly_signed_webhook_is_not_proof_of_payment(world, online):
    """The webhook claims success, but the provider's own status says pending: nothing is marked paid."""
    order = place(world, online)
    pay = Payment.unscoped.get(pk=initiate(world, order["id"]).data["id"])
    assert webhook(pay.provider_ref).status_code == 200  # valid signature, provider has NOT confirmed
    pay.refresh_from_db()
    assert pay.status == "pending" and Order.unscoped.get(pk=order["id"]).status == Status.PAYMENT_PROCESSING
    assert Receipt.unscoped.count() == 0


def test_unknown_reference_and_malformed_events_are_handled(world, online):
    assert webhook("SIM-unknown").data["data"]["processed"] is False
    raw = b"not json"
    r = APIClient(HTTP_HOST=host()).post(P + "webhooks/simulated/", data=raw, content_type="application/json", HTTP_X_SIGNATURE=SIM.sign(raw))
    assert r.status_code == 400


def test_amount_mismatch_is_flagged_not_paid(world, online):
    order, pay, ref = paid_order(world, online)
    SIM.set_outcome(ref, "succeeded", amount="1.00")
    webhook(ref)
    pay.refresh_from_db()
    o = Order.unscoped.get(pk=order["id"])
    assert pay.status == "mismatch" and o.status == Status.PAYMENT_PROCESSING and o.amount_paid == 0 and Receipt.unscoped.count() == 0
    rows = client_for(client_user(world, "admin_a"), "alpha").get(P + "manage/", {"status": "mismatch"}).data["results"]
    assert [r["id"] for r in rows] == [pay.pk]
    assert AuditLog.objects.filter(action="payment.mismatch").exists()


def client_user(world, who):
    return world[who]


def test_failed_payment_returns_order_to_awaiting_and_allows_a_new_attempt(world, online):
    order, pay, ref = paid_order(world, online, outcome="failed")
    webhook(ref)
    pay.refresh_from_db()
    assert pay.status == "failed" and Order.unscoped.get(pk=order["id"]).status == Status.AWAITING_PAYMENT
    second = initiate(world, order["id"], key="retry")
    assert second.status_code == 201 and second.data["id"] != pay.pk


def test_customer_poll_verifies_with_provider_and_is_private(world, online):
    order, pay, ref = paid_order(world, online)
    c = client_for(world["cust_a"], "alpha")
    assert c.get(f"{P}my/{pay.pk}/").data["status"] == "succeeded"  # no webhook needed
    assert Order.unscoped.get(pk=order["id"]).status == Status.CONFIRMED
    assert client_for(world["cust2_a"], "alpha").get(f"{P}my/{pay.pk}/").status_code == 404


def test_reconciliation_settles_lost_webhooks_only(world, online):
    order, pay, ref = paid_order(world, online)
    assert services.reconcile_pending(older_than_minutes=60) == []  # too recent
    assert services.reconcile_pending(older_than_minutes=0) == ["succeeded"]
    assert services.reconcile_pending(older_than_minutes=0) == []  # nothing left, no double processing
    assert Receipt.unscoped.count() == 1


# ---- cash --------------------------------------------------------------------------------------
def ensure_shift(world, who):
    """Cashiers must have an open shift at the branch to take cash (Phase 7 rule)."""
    from apps.accounts.models import Membership
    from apps.cashier.models import Shift

    u = world[who]
    m = Membership.objects.get(user=u, restaurant=world["a"])
    branch = m.branches.first()
    if m.role == "cashier" and branch and not Shift.unscoped.filter(cashier=u, status="open").exists():
        Shift.unscoped.create(restaurant=world["a"], branch=branch, cashier=u, opening_cash=Decimal("0.00"))


def cash(world, who, order_id, received, key="cash-1"):
    ensure_shift(world, who)
    return client_for(world[who], "alpha").post(P + "cash/", {"order_id": order_id, "amount_received": received}, format="json", HTTP_IDEMPOTENCY_KEY=key)


def test_cashier_records_cash_with_change_and_receipt(world, shop):
    order = place(world, shop, method="cash")
    r = cash(world, "cashier_a1", order["id"], "20.00")
    assert r.status_code == 201 and r.data["change_given"] == "9.07" and r.data["status"] == "succeeded"  # total 10.93
    o = Order.unscoped.get(pk=order["id"])
    assert (o.status, o.payment_status, o.amount_paid) == (Status.CONFIRMED, "paid", Decimal("10.93"))
    rc = Receipt.unscoped.get(pk=r.data["receipt_id"])
    assert rc.data["cashier"] == "cash1" and rc.data["payment"]["received"] == "20.00" and rc.data["payment"]["change"] == "9.07"
    assert cash(world, "cashier_a1", order["id"], "20.00").data["id"] == r.data["id"] and Payment.unscoped.count() == 1  # idempotent
    assert cash(world, "cashier_a1", order["id"], "20.00", key="again").status_code == 400  # already paid


def test_cash_rules_and_access(world, shop):
    order = place(world, shop, method="cash")
    assert cash(world, "cashier_a1", order["id"], "5.00").status_code == 400  # not enough
    assert cash(world, "cashier_a2", order["id"], "20.00").status_code == 400  # other branch: order not visible
    for who in ("kitchen_a1", "delivery_a1", "cust_a"):
        assert cash(world, who, order["id"], "20.00").status_code == 403
    assert client_for(world["cashier_a1"], "alpha").post(P + "cash/", {"order_id": order["id"], "amount_received": "20"}, format="json").status_code == 400  # no key
    assert cash(world, "mgr_a1", order["id"], "11.00").status_code == 201
    assert Payment.unscoped.count() == 1


def test_cash_blocked_while_an_online_payment_is_in_flight_or_order_cancelled(world, online):
    order = place(world, online)
    initiate(world, order["id"])
    assert cash(world, "cashier_a1", order["id"], "20.00").status_code == 400
    cancelled = place(world, online, method="cash", who="cust2_a")
    client_for(world["cashier_a1"], "alpha").post(f"{O}manage/{cancelled['id']}/transition/", {"status": "cancelled", "note": "x"}, format="json")
    assert cash(world, "cashier_a1", cancelled["id"], "20.00", key="k2").status_code == 400


# ---- receipts ----------------------------------------------------------------------------------
def test_receipt_access_pdf_and_immutability(world, shop):
    order = place(world, shop, method="cash")
    rid = cash(world, "cashier_a1", order["id"], "20.00").data["receipt_id"]
    owner = client_for(world["cust_a"], "alpha")
    d = owner.get(f"{P}receipts/{rid}/").data
    assert d["number"] == "RCT-000001" and d["items"][0]["name"] == "Rice" and d["restaurant"]["name"] == "Alpha"
    pdf = owner.get(f"{P}receipts/{rid}/pdf/")
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert client_for(world["cashier_a1"], "alpha").get(f"{P}receipts/{rid}/").status_code == 200
    assert client_for(world["admin_a"], "alpha").get(f"{P}receipts/{rid}/pdf/").status_code == 200
    for who, slug in (("cust2_a", "alpha"), ("cashier_a2", "alpha"), ("mgr_a2", "alpha"), ("kitchen_a1", "alpha"), ("delivery_a1", "alpha")):
        assert client_for(world[who], slug).get(f"{P}receipts/{rid}/").status_code == 404, who
        assert client_for(world[who], slug).get(f"{P}receipts/{rid}/pdf/").status_code == 404, who
    assert client_for(world["admin_b"], "bravo").get(f"{P}receipts/{rid}/").status_code == 404
    assert APIClient(HTTP_HOST=host("alpha")).get(f"{P}receipts/{rid}/pdf/").status_code == 401
    rc = Receipt.unscoped.get(pk=rid)
    with pytest.raises(PermissionError):
        rc.delete()
    rc.number = "HACK"
    with pytest.raises(PermissionError):
        rc.save()


def test_receipt_is_a_snapshot_and_numbers_are_sequential_per_restaurant(world, shop):
    a = cash(world, "cashier_a1", place(world, shop, method="cash")["id"], "20.00", key="1").data["receipt_id"]
    shop["rice"].name, shop["rice"].base_price = "Changed", Decimal("99.00")
    shop["rice"].save()
    b = cash(world, "cashier_a1", place(world, shop, method="cash", who="cust2_a")["id"], "200.00", key="2")
    assert client_for(world["cust_a"], "alpha").get(f"{P}receipts/{a}/").data["items"][0]["name"] == "Rice"
    assert b.status_code == 201 and Receipt.unscoped.get(pk=b.data["receipt_id"]).number == "RCT-000002"


def test_customer_order_detail_links_payment_and_receipt(world, shop):
    order = place(world, shop, method="cash")
    rid = cash(world, "cashier_a1", order["id"], "20.00").data["receipt_id"]
    d = client_for(world["cust_a"], "alpha").get(f"{O}my/{order['id']}/").data
    assert d["payment_status"] == "paid" and d["payments"][0]["receipt_id"] == rid and d["payments"][0]["status"] == "succeeded"


# ---- refunds -----------------------------------------------------------------------------------
def refund(world, who, payment_id, amount, reason="customer unhappy", key="r1"):
    return client_for(world[who], "alpha").post(f"{P}{payment_id}/refund/", {"amount": amount, "reason": reason}, format="json", HTTP_IDEMPOTENCY_KEY=key)


def test_partial_then_full_refund_updates_order_and_never_over_refunds(world, shop):
    order = place(world, shop, method="cash")
    pay = cash(world, "cashier_a1", order["id"], "10.93").data
    for who in ("cashier_a1", "kitchen_a1", "cust_a"):
        assert refund(world, who, pay["id"], "1.00", key=who).status_code == 403
    assert refund(world, "mgr_a1", pay["id"], "4.00", key="p1").status_code == 201
    assert refund(world, "mgr_a1", pay["id"], "7.00", key="p2").status_code == 400  # only 6.93 left
    assert refund(world, "mgr_a1", pay["id"], "0", key="p3").status_code == 400
    assert refund(world, "mgr_a1", pay["id"], "6.93", key="p4").status_code == 201
    o = Order.unscoped.get(pk=order["id"])
    assert o.amount_paid == 0 and o.payment_status == "refunded"
    assert refund(world, "mgr_a1", pay["id"], "0.01", key="p5").status_code == 400
    assert AuditLog.objects.filter(action="payment.refunded").count() == 2
    assert any("Refund" in m["subject"] for m in ConsoleProvider.outbox if m["to"] == "cust@a.com")


def test_refund_idempotency_and_branch_scope(world, shop):
    pay = cash(world, "cashier_a1", place(world, shop, method="cash")["id"], "20.00").data
    a = refund(world, "mgr_a1", pay["id"], "2.00", key="same")
    b = refund(world, "mgr_a1", pay["id"], "2.00", key="same")
    assert a.status_code == b.status_code == 201 and a.data == b.data
    from apps.payments.models import Refund
    assert Refund.unscoped.count() == 1
    assert refund(world, "mgr_a2", pay["id"], "1.00", key="o").status_code == 400  # other branch's payment is invisible
    assert client_for(world["admin_b"], "bravo").post(f"{P}{pay['id']}/refund/", {"amount": "1", "reason": "abc"}, format="json", HTTP_IDEMPOTENCY_KEY="z").status_code == 400


def test_completed_order_full_refund_walks_refund_pending_to_refunded(world, shop):
    order = place(world, shop, method="cash")
    pay = cash(world, "cashier_a1", order["id"], "10.93").data
    for to in ("received", "preparing", "ready_for_pickup", "completed"):
        client_for(world["mgr_a1"], "alpha").post(f"{O}manage/{order['id']}/transition/", {"status": to}, format="json")
    assert refund(world, "mgr_a1", pay["id"], "10.93").status_code == 201
    o = Order.unscoped.get(pk=order["id"])
    assert o.status == Status.REFUNDED and o.payment_status == "refunded"
    assert [h.to_status for h in o.history.all()][-2:] == ["refund_pending", "refunded"]


def test_refunded_active_order_can_then_be_cancelled(world, shop):
    order = place(world, shop, method="cash")
    pay = cash(world, "cashier_a1", order["id"], "10.93").data
    assert client_for(world["mgr_a1"], "alpha").post(f"{O}manage/{order['id']}/transition/", {"status": "cancelled", "note": "x"}, format="json").status_code == 400
    refund(world, "mgr_a1", pay["id"], "10.93")
    assert client_for(world["mgr_a1"], "alpha").post(f"{O}manage/{order['id']}/transition/", {"status": "cancelled", "note": "changed mind"}, format="json").status_code == 200


def test_online_refund_goes_through_the_provider_and_failures_change_nothing(world, online, monkeypatch):
    order, pay, ref = paid_order(world, online)
    webhook(ref)
    pay.refresh_from_db()

    def boom(self, **kw):
        raise ProviderError("down")

    monkeypatch.setattr(SimulatedProvider, "refund", boom)
    assert refund(world, "mgr_a1", pay.pk, "3.00", key="f").status_code == 400
    from apps.payments.models import Refund
    assert Refund.unscoped.count() == 0 and Order.unscoped.get(pk=order["id"]).amount_paid == Decimal(order["total"])
    monkeypatch.undo()
    r = refund(world, "mgr_a1", pay.pk, "3.00", key="g")
    assert r.status_code == 201 and Refund.unscoped.get().provider_ref.startswith("SIMREF-")


def test_staff_payment_list_is_manager_only_and_branch_scoped(world, shop):
    p1 = cash(world, "cashier_a1", place(world, shop, method="cash")["id"], "20.00", key="1").data
    p2 = cash(world, "cashier_a2", place(world, shop, method="cash", who="cust2_a", branch="a2")["id"], "20.00", key="2").data
    ids = lambda who: sorted(r["id"] for r in client_for(world[who], "alpha").get(P + "manage/").data["results"])  # noqa: E731
    assert ids("mgr_a1") == [p1["id"]] and ids("mgr_a2") == [p2["id"]] and ids("admin_a") == sorted([p1["id"], p2["id"]])
    for who in ("cashier_a1", "kitchen_a1", "cust_a"):
        assert client_for(world[who], "alpha").get(P + "manage/").status_code == 403
    assert client_for(world["admin_b"], "bravo").get(P + "manage/").data["results"] == []


def test_dev_simulator_endpoint_is_unavailable_when_not_debug(world, online, settings):
    settings.DEBUG = False
    assert APIClient(HTTP_HOST=host()).post(P + "dev/simulate/", {"provider_ref": "x"}, format="json").status_code == 404
