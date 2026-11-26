import json
from decimal import Decimal

import pytest

from apps.accounts.models import User
from apps.cashier.models import Shift, ShiftAdjustment
from apps.core.models import AuditLog
from apps.notifications.providers import ConsoleProvider
from apps.orders.models import Order, Status
from apps.payments.models import Payment, Receipt
from apps.payments.providers import SimulatedProvider

from .conftest import client_for
from .test_phase5_orders import clean, line, shop  # noqa: F401  (fixtures)

K = "/api/v1/cashier/"
SIM = SimulatedProvider()


def api(world, who, slug="alpha"):
    return client_for(world[who], slug)


def open_shift(world, who="cashier_a1", cash="100.00", branch=None):
    body = {"opening_cash": cash, **({"branch_id": branch} if branch else {})}
    return api(world, who).post(K + "shift/open/", body, format="json")


def order_body(shop, **over):
    return {"items": [line(shop["rice"], 2)], "fulfilment": "dine_in", "payment": "cash", "amount_received": "50.00", **over}


def place(world, shop, who="cashier_a1", key="o1", **over):
    return api(world, who).post(K + "orders/", order_body(shop, **over), format="json", HTTP_IDEMPOTENCY_KEY=key)


# ---- opening shifts ----------------------------------------------------------------------------
def test_open_shift_rules(world):
    r = open_shift(world)
    assert r.status_code == 201 and r.data["status"] == "open" and r.data["opening_cash"] == "100.00" and r.data["branch_id"] == world["a1"].pk
    assert open_shift(world).status_code == 400  # one open shift per cashier
    assert open_shift(world, "cashier_a2", branch=world["a1"].pk).status_code == 400  # not their branch
    assert open_shift(world, "mgr_a1", cash="-5").status_code == 400
    for who in ("kitchen_a1", "delivery_a1", "cust_a"):
        assert open_shift(world, who).status_code == 403
    assert api(world, "cashier_a1").get(K + "shift/current/").data["shift"]["id"] == r.data["id"]
    assert AuditLog.objects.filter(action="shift.opened").count() == 1


def test_one_open_shift_is_enforced_by_the_database(world):
    from django.db import IntegrityError, transaction
    Shift.unscoped.create(restaurant=world["a"], branch=world["a1"], cashier=world["cashier_a1"], opening_cash=Decimal("0"))
    with pytest.raises(IntegrityError), transaction.atomic():
        Shift.unscoped.create(restaurant=world["a"], branch=world["a1"], cashier=world["cashier_a1"], opening_cash=Decimal("0"))


def test_cashier_needs_an_open_shift_to_take_cash_but_managers_do_not(world, shop):
    assert place(world, shop, key="a", payment="pay_later", amount_received=None).status_code == 201  # no payment, no shift needed
    r = place(world, shop, key="b")
    assert r.status_code == 400 and "shift" in json.dumps(r.data).lower()
    assert Order.unscoped.filter(source="cashier").count() == 1  # the failed attempt rolled back entirely
    assert place(world, shop, who="mgr_a1", key="c").status_code == 201


# ---- till arithmetic ---------------------------------------------------------------------------
def test_expected_cash_variance_and_closing_rules(world, shop):
    sid = open_shift(world, cash="100.00").data["id"]
    r = place(world, shop, key="s1", amount_received="50.00")  # 2 x 10.10 + 8.25% tax = 21.87
    assert r.status_code == 201 and r.data["change_given"] == "28.13"
    pid = r.data["payment"]["id"]
    cur = api(world, "cashier_a1").get(K + "shift/current/").data["shift"]
    assert cur["totals"]["cash_sales"] == "21.87" and cur["expected_cash"] == "121.87"
    # manager refunds part of it: cash leaves the till that took it
    assert api(world, "mgr_a1").post(f"/api/v1/payments/{pid}/refund/", {"amount": "5.00", "reason": "cold food"}, format="json", HTTP_IDEMPOTENCY_KEY="rf").status_code == 201
    assert api(world, "cashier_a1").get(K + "shift/current/").data["shift"]["expected_cash"] == "116.87"
    c = api(world, "cashier_a1")
    assert c.post(f"{K}shifts/{sid}/close/", {"actual_cash": "110.00"}, format="json").status_code == 400  # variance needs an explanation
    ok = c.post(f"{K}shifts/{sid}/close/", {"actual_cash": "110.00", "notes": "gave a customer change from my pocket"}, format="json")
    assert ok.status_code == 200
    assert (ok.data["status"], ok.data["expected_cash"], ok.data["actual_cash"], ok.data["variance"]) == ("closed", "116.87", "110.00", "-6.87")
    assert c.post(f"{K}shifts/{sid}/close/", {"actual_cash": "1"}, format="json").status_code == 400  # already closed
    assert c.get(K + "shift/current/").data["shift"] is None
    assert AuditLog.objects.filter(action="shift.closed").get().metadata["variance"] == "-6.87"


def test_exact_count_closes_without_notes_and_closed_shift_is_immutable(world, shop):
    sid = open_shift(world, cash="20.00").data["id"]
    r = api(world, "cashier_a1").post(f"{K}shifts/{sid}/close/", {"actual_cash": "20.00"}, format="json")
    assert r.status_code == 200 and r.data["variance"] == "0.00"
    s = Shift.unscoped.get(pk=sid)
    s.opening_cash = Decimal("999")
    with pytest.raises(PermissionError):
        s.save()
    with pytest.raises(PermissionError):
        s.delete()


def test_late_refund_after_close_does_not_change_the_closed_shift(world, shop):
    sid = open_shift(world).data["id"]
    pid = place(world, shop, key="x").data["payment"]["id"]
    api(world, "cashier_a1").post(f"{K}shifts/{sid}/close/", {"actual_cash": "121.87"}, format="json")
    before = Shift.unscoped.get(pk=sid).expected_cash
    assert api(world, "mgr_a1").post(f"/api/v1/payments/{pid}/refund/", {"amount": "5.00", "reason": "late"}, format="json", HTTP_IDEMPOTENCY_KEY="late").status_code == 201
    s = Shift.unscoped.get(pk=sid)
    assert s.expected_cash == before and s.refunds.count() == 0


def test_other_cashiers_cannot_close_or_see_my_shift(world):
    sid = open_shift(world).data["id"]
    other = api(world, "cashier_a2")
    assert other.post(f"{K}shifts/{sid}/close/", {"actual_cash": "1"}, format="json").status_code == 400
    assert other.get(f"{K}shifts/{sid}/").status_code == 404
    assert Shift.unscoped.get(pk=sid).status == "open"


# ---- adjustments (independent approval) --------------------------------------------------------
def adjust(world, sid, kind="cash_out", amount="10.00", who="cashier_a1"):
    return api(world, who).post(f"{K}shifts/{sid}/adjustments/", {"kind": kind, "amount": amount, "reason": "bank drop"}, format="json")


def decide(world, who, aid, approve=True):
    return api(world, who).post(f"{K}adjustments/{aid}/decide/", {"approve": approve, "note": "ok"}, format="json")


def test_adjustment_needs_approval_by_someone_else_and_changes_expected_cash(world):
    sid = open_shift(world, cash="100.00").data["id"]
    a = adjust(world, sid, "cash_out", "30.00")
    assert a.status_code == 201 and a.data["status"] == "pending"
    cur = lambda: api(world, "cashier_a1").get(K + "shift/current/").data["shift"]["expected_cash"]  # noqa: E731
    assert cur() == "100.00"  # not counted until approved
    assert api(world, "cashier_a1").post(f"{K}shifts/{sid}/close/", {"actual_cash": "100"}, format="json").status_code == 400  # pending blocks closing
    assert decide(world, "cashier_a1", a.data["id"]).status_code == 403  # cashiers never approve
    assert decide(world, "mgr_a2", a.data["id"]).status_code == 400  # other branch's manager cannot see it
    assert [x["id"] for x in api(world, "mgr_a1").get(K + "adjustments/pending/").data] == [a.data["id"]]
    assert api(world, "mgr_a2").get(K + "adjustments/pending/").data == []
    assert decide(world, "mgr_a1", a.data["id"]).data["status"] == "approved"
    assert cur() == "70.00"
    assert decide(world, "mgr_a1", a.data["id"]).status_code == 400  # decided once
    b = adjust(world, sid, "cash_in", "5.00")
    decide(world, "admin_a", b.data["id"])
    assert cur() == "75.00"
    c = adjust(world, sid, "cash_out", "40.00")
    assert decide(world, "mgr_a1", c.data["id"], approve=False).data["status"] == "rejected"
    assert cur() == "75.00"  # rejected adjustments never count
    assert api(world, "cashier_a1").post(f"{K}shifts/{sid}/close/", {"actual_cash": "75.00"}, format="json").data["variance"] == "0.00"
    assert AuditLog.objects.filter(action__startswith="shift.adjustment_").count() == 6


def test_a_manager_cannot_approve_their_own_adjustment(world):
    sid = open_shift(world, "mgr_a1").data["id"]
    a = adjust(world, sid, who="mgr_a1")
    assert decide(world, "mgr_a1", a.data["id"]).status_code == 400
    assert decide(world, "admin_a", a.data["id"]).status_code == 200


def test_adjustment_validation_and_closed_shift(world):
    sid = open_shift(world).data["id"]
    assert adjust(world, sid, amount="0").status_code == 400
    assert adjust(world, sid, amount="-5").status_code == 400
    assert adjust(world, sid, kind="steal").status_code == 400
    assert adjust(world, sid, who="cashier_a2").status_code == 400  # not their shift
    api(world, "cashier_a1").post(f"{K}shifts/{sid}/close/", {"actual_cash": "100"}, format="json")
    assert adjust(world, sid).status_code == 400


# ---- visibility of shifts ----------------------------------------------------------------------
def test_shift_lists_are_scoped(world):
    s1, s2 = open_shift(world).data["id"], open_shift(world, "cashier_a2").data["id"]
    ids = lambda who: sorted(x["id"] for x in api(world, who).get(K + "shifts/").data["results"])  # noqa: E731
    assert ids("cashier_a1") == [s1] and ids("cashier_a2") == [s2]
    assert ids("mgr_a1") == [s1] and ids("mgr_a2") == [s2] and ids("admin_a") == sorted([s1, s2])
    assert api(world, "mgr_a1").get(f"{K}shifts/{s2}/").status_code == 404
    assert api(world, "mgr_a2").get(f"{K}shifts/{s2}/").status_code == 200
    assert api(world, "admin_b", "bravo").get(K + "shifts/").data["results"] == []
    for who in ("kitchen_a1", "cust_a"):
        assert api(world, who).get(K + "shifts/").status_code == 403


def test_shift_report_lists_its_transactions(world, shop):
    sid = open_shift(world).data["id"]
    place(world, shop, key="r1")
    d = api(world, "mgr_a1").get(f"{K}shifts/{sid}/").data
    assert len(d["payments"]) == 1 and d["payments"][0]["received"] == "50.00" and d["totals"]["cash_transactions"] == "1"


# ---- in-person orders --------------------------------------------------------------------------
def test_cashier_creates_a_guest_order_paid_in_cash_with_receipt_and_no_account(world, shop):
    open_shift(world)
    users = User.objects.count()
    r = place(world, shop, contact_name="Mr Bangura", contact_phone="+23276000111", contact_email="walk@in.com", notes="table 4")
    assert r.status_code == 201, r.data
    o = Order.unscoped.get()
    assert (o.source, o.customer_id, o.cashier_id, o.status, o.payment_status, o.fulfilment) == ("cashier", None, world["cashier_a1"].pk, Status.CONFIRMED, "paid", "dine_in")
    assert o.contact_name == "Mr Bangura" and o.branch_id == world["a1"].pk and User.objects.count() == users  # no account created
    rc = Receipt.unscoped.get()
    assert rc.data["cashier"] == "cash1" and rc.data["payment"]["change"] == r.data["change_given"] == "28.13"
    assert [m for m in ConsoleProvider.outbox if m["to"] == "walk@in.com"]  # emailed because an address was given
    # the guest order is a staff record only
    assert api(world, "cust_a").get("/api/v1/orders/my/").data["results"] == []
    assert api(world, "cashier_a1").get(f"/api/v1/orders/manage/{o.pk}/").status_code == 200


def test_order_creation_is_idempotent_and_ignores_client_prices(world, shop):
    open_shift(world)
    body = order_body(shop, total="0.01", subtotal="0.01")
    body["items"][0]["price"] = "0.01"
    a = api(world, "cashier_a1").post(K + "orders/", body, format="json", HTTP_IDEMPOTENCY_KEY="same")
    b = api(world, "cashier_a1").post(K + "orders/", body, format="json", HTTP_IDEMPOTENCY_KEY="same")
    assert a.status_code == b.status_code == 201 and a.data == b.data
    assert Order.unscoped.count() == 1 and Payment.unscoped.count() == 1 and Order.unscoped.get().total == Decimal("21.87")
    assert api(world, "cashier_a1").post(K + "orders/", body, format="json").status_code == 400  # no key


def test_pay_later_and_validation(world, shop):
    open_shift(world)
    r = place(world, shop, key="pl", payment="pay_later", amount_received=None)
    assert r.status_code == 201 and Order.unscoped.get().status == Status.AWAITING_PAYMENT and Payment.unscoped.count() == 0
    assert place(world, shop, key="v1", amount_received=None).status_code == 400  # cash needs an amount
    assert place(world, shop, key="v2", amount_received="1.00").status_code == 400  # less than due
    assert place(world, shop, key="v3", fulfilment="delivery").status_code == 400  # delivery needs address + phone
    assert place(world, shop, key="v4", fulfilment="delivery", contact_phone="+23276111222", address={"line1": "1 St", "city": "Bo"}).status_code == 201
    bad = {"items": [{"product_id": shop["bdish"].pk, "quantity": 1}], "payment": "pay_later"}
    assert api(world, "cashier_a1").post(K + "orders/", bad, format="json", HTTP_IDEMPOTENCY_KEY="v5").status_code == 400  # other restaurant's product


def test_stock_is_deducted_for_in_person_orders(world, shop):
    open_shift(world)
    assert place(world, shop, key="st", items=[line(shop["fish"], 2)]).status_code == 201
    shop["fish"].refresh_from_db()
    assert shop["fish"].stock_quantity == 1
    assert place(world, shop, key="st2", items=[line(shop["fish"], 2)]).status_code == 400


def test_in_person_order_access_rules(world, shop):
    open_shift(world)
    for who in ("kitchen_a1", "delivery_a1", "cust_a"):
        assert api(world, who).post(K + "orders/", order_body(shop), format="json", HTTP_IDEMPOTENCY_KEY=who).status_code == 403
    r = api(world, "cashier_a1").post(K + "orders/", order_body(shop, branch_id=world["a2"].pk), format="json", HTTP_IDEMPOTENCY_KEY="b")
    assert r.status_code == 400  # cashiers work only at their own branch
    assert api(world, "admin_a").post(K + "orders/", order_body(shop, branch_id=world["a2"].pk, payment="pay_later", amount_received=None), format="json", HTTP_IDEMPOTENCY_KEY="c").status_code == 201


def test_in_person_mobile_money_starts_a_pending_provider_payment(world, shop):
    shop["settings"].online_payments_enabled = True
    shop["settings"].save()
    open_shift(world)
    r = place(world, shop, key="mm", payment="mobile_money", amount_received=None, payer_phone="+23276123456")
    assert r.status_code == 201 and r.data["payment"]["status"] == "pending"
    o = Order.unscoped.get()
    assert o.status == Status.PAYMENT_PROCESSING and o.payment_method == "mobile_money" and o.payment_status == "unpaid"
    pay = Payment.unscoped.get()
    SIM.set_outcome(pay.provider_ref, "succeeded")
    from apps.payments.services import settle_payment
    settle_payment(pay.pk)
    o.refresh_from_db()
    assert o.status == Status.CONFIRMED and Receipt.unscoped.count() == 1
    d = api(world, "cashier_a1").get(K + "dashboard/").data
    assert d["periods"]["today"]["mobile_money"] == "21.87"  # attributed to the cashier who entered the order
    cur = api(world, "cashier_a1").get(K + "shift/current/").data["shift"]
    assert cur["totals"]["mobile_money_sales"] == "21.87" and cur["totals"]["cash_sales"] == "0.00"
    assert cur["expected_cash"] == "100.00"  # mobile money never enters the cash drawer


def test_mobile_money_refused_when_online_payments_are_off(world, shop):
    from apps.tenants.models import RestaurantSettings

    RestaurantSettings.objects.filter(restaurant=world["a"]).update(online_payments_enabled=False)  # the restaurant switched it off
    open_shift(world)
    assert place(world, shop, key="mm", payment="mobile_money", amount_received=None, payer_phone="+23276123456").status_code == 400
    assert Order.unscoped.count() == 0


# ---- personal dashboard ------------------------------------------------------------------------
def test_dashboard_is_personal(world, shop):
    open_shift(world)
    open_shift(world, "cashier_a2")
    place(world, shop, key="d1")
    place(world, shop, key="d2", amount_received="30.00")
    place(world, shop, who="cashier_a2", key="d3", branch_id=world["a2"].pk)
    d1 = api(world, "cashier_a1").get(K + "dashboard/").data
    d2 = api(world, "cashier_a2").get(K + "dashboard/").data
    assert d1["periods"]["today"] == {"total": "43.74", "cash": "43.74", "mobile_money": "0.00", "transactions": 2, "orders_processed": 2}
    assert d2["periods"]["today"]["total"] == "21.87" and d2["periods"]["today"]["transactions"] == 1
    assert len(d1["recent_transactions"]) == 2 and len(d2["recent_orders"]) == 1
    assert {o["id"] for o in d1["recent_orders"]}.isdisjoint({o["id"] for o in d2["recent_orders"]})
    assert d1["periods"]["week"]["total"] == d1["periods"]["month"]["total"] == "43.74"
    assert d1["shift"]["id"] != d2["shift"]["id"]
    for who in ("kitchen_a1", "cust_a"):
        assert api(world, who).get(K + "dashboard/").status_code == 403
