from decimal import Decimal

import pytest

from apps.core.models import AuditLog
from apps.customers.models import CustomerNote
from apps.orders.models import Order

from .conftest import client_for
from .test_phase5_orders import clean, shop  # noqa: F401
from .test_phase8_management import mk_order

C = "/api/v1/cashier/"


def api(world, who, slug="alpha"):
    return client_for(world[who], slug)


def sale(world, who, items, discount=None, key="k1", **over):
    body = {"items": items, "fulfilment": "pickup", "payment": "cash", "amount_received": "500.00", "branch_id": world["a1"].pk, **over}
    if discount:
        body["discount"] = discount
    return api(world, who).post(C + "orders/", body, format="json", HTTP_IDEMPOTENCY_KEY=key)


def open_shift(world, who="cashier_a1"):
    return api(world, who).post(C + "shift/open/", {"opening_cash": "10.00", "branch_id": world["a1"].pk}, format="json")


# ---------------- discounts ----------------
def test_percent_discount_reduces_subtotal_before_tax(world, shop, clean):  # noqa: F811
    open_shift(world)
    r = api(world, "cashier_a1").post(C + "quote/", {"items": [{"product_id": shop["rice"].pk, "quantity": 2}], "discount": {"type": "percent", "value": "10", "reason": "Regular customer"}}, format="json")
    assert r.status_code == 200, r.content
    d = r.json()["data"]
    # subtotal 20.20, 10% = 2.02, taxable 18.18 x 8.25% = 1.49985 -> 1.50, total 19.68
    assert d["subtotal"] == "20.20" and d["discount_total"] == "2.02" and d["tax_total"] == "1.50" and d["total"] == "19.68"


def test_amount_discount_and_order_records_who_and_why(world, shop, clean):  # noqa: F811
    open_shift(world, "cashier_a1")
    r = sale(world, "mgr_a1", [{"product_id": shop["rice"].pk, "quantity": 2}], {"type": "amount", "value": "5.00", "reason": "Birthday"})
    assert r.status_code == 201, r.content
    o = Order.unscoped.get(number=r.json()["data"]["order"]["number"])
    assert o.discount_total == Decimal("5.00") and o.discount_reason == "Birthday" and o.discount_by == world["mgr_a1"]
    assert o.total == o.subtotal - o.discount_total + o.tax_total
    assert AuditLog.objects.filter(action="order.discount_applied", metadata__reason="Birthday").exists()


def test_cashier_is_capped_manager_is_not(world, shop, clean):  # noqa: F811
    open_shift(world)
    big = {"type": "percent", "value": "25", "reason": "Complaint"}
    items = [{"product_id": shop["rice"].pk, "quantity": 2}]
    r = sale(world, "cashier_a1", items, big, key="c1")
    assert r.status_code == 400 and "need a manager" in str(r.json())
    assert not Order.unscoped.exists()
    assert sale(world, "cashier_a1", items, {"type": "percent", "value": "10", "reason": "Loyalty"}, key="c2").status_code == 201
    assert sale(world, "mgr_a1", items, big, key="m1").status_code == 201


def test_discount_validation(world, shop, clean):  # noqa: F811
    open_shift(world)
    items = [{"product_id": shop["rice"].pk, "quantity": 1}]
    c = api(world, "mgr_a1")
    for bad in ({"type": "percent", "value": "101", "reason": "x y z"}, {"type": "amount", "value": "999.00", "reason": "too big"}, {"type": "amount", "value": "0", "reason": "zero"},
                {"type": "amount", "value": "1.00", "reason": "  "}, {"type": "weird", "value": "1", "reason": "abc"}):
        assert c.post(C + "quote/", {"items": items, "discount": bad}, format="json").status_code == 400, bad


def test_public_quote_and_checkout_ignore_discounts(world, shop, clean):  # noqa: F811
    from rest_framework.test import APIClient

    from .conftest import host

    pub = APIClient(HTTP_HOST=host("alpha"))
    r = pub.post("/api/v1/orders/quote/", {"items": [{"product_id": shop["rice"].pk, "quantity": 1}], "fulfilment": "pickup", "discount": {"type": "percent", "value": "100", "reason": "hack"}}, format="json")
    assert r.json()["data"]["discount_total"] == "0.00"
    c = api(world, "cust_a")
    r = c.post("/api/v1/orders/checkout/", {"items": [{"product_id": shop["rice"].pk, "quantity": 1}], "fulfilment": "pickup", "payment_method": "cash", "contact_phone": "+23276123456",
                                          "branch_id": world["a1"].pk, "discount": {"type": "percent", "value": "100", "reason": "hack"}}, format="json", HTTP_IDEMPOTENCY_KEY="d1")
    assert r.status_code == 201
    assert Order.unscoped.get().discount_total == 0


def test_customers_and_kitchen_cannot_use_staff_quote(world, shop, clean):  # noqa: F811
    for who in ("cust_a", "kitchen_a1"):
        assert api(world, who).post(C + "quote/", {"items": [{"product_id": shop["rice"].pk, "quantity": 1}]}, format="json").status_code == 403


def test_admin_configures_cashier_limit_and_timezone(world, shop, clean):  # noqa: F811
    a = api(world, "admin_a")
    assert a.patch("/api/v1/catalog/site/", {"cashier_max_discount_percent": "30"}, format="json").status_code == 200
    open_shift(world)
    assert sale(world, "cashier_a1", [{"product_id": shop["rice"].pk, "quantity": 2}], {"type": "percent", "value": "25", "reason": "Event"}).status_code == 201
    assert a.patch("/api/v1/catalog/site/", {"timezone": "Mars/Base"}, format="json").status_code == 400
    assert a.patch("/api/v1/catalog/site/", {"timezone": "Africa/Freetown"}, format="json").json()["data"]["timezone"] == "Africa/Freetown"
    assert api(world, "mgr_a1").patch("/api/v1/catalog/site/", {"timezone": "UTC"}, format="json").status_code == 403


# ---------------- kitchen list with items ----------------
def test_staff_order_list_can_include_items_in_one_request(world, shop, clean):  # noqa: F811
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    for i in range(6):
        mk_order(world, world["a1"], "10.00", status="received", item=f"Dish {i}", qty=2)
    c = api(world, "kitchen_a1")
    with CaptureQueriesContext(connection) as ctx:
        r = c.get("/api/v1/orders/manage/", {"active": 1, "include": "items"})
    rows = r.json()["data"]["results"]
    assert r.status_code == 200 and len(rows) == 6 and all(x["items"] and "allowed_transitions" in x for x in rows)
    assert {"preparing"} <= {t["status"] for t in rows[0]["allowed_transitions"]}
    assert len(ctx) < 20
    plain = c.get("/api/v1/orders/manage/", {"active": 1}).json()["data"]["results"][0]
    assert "items" not in plain
    assert api(world, "cashier_a2").get("/api/v1/orders/manage/", {"include": "items"}).json()["data"]["results"] == []  # branch scope still applies


# ---------------- customer directory ----------------
def test_directory_search_scope_and_stats(world, shop, clean):  # noqa: F811
    mk_order(world, world["a1"], "30.00", customer=world["cust_a"], paid="30.00")
    mk_order(world, world["a2"], "50.00", customer=world["cust_a"], paid="50.00")
    mk_order(world, world["a2"], "20.00", customer=world["cust2_a"], paid="20.00")
    admin = api(world, "admin_a").get("/api/v1/customers/directory/").json()["data"]
    by = {r["email"]: r for r in admin["results"]}
    assert by["cust@a.com"]["orders"] == 2 and by["cust@a.com"]["spent"] == "80.00" and by["cust2@a.com"]["orders"] == 1
    mgr = api(world, "mgr_a1").get("/api/v1/customers/directory/").json()["data"]["results"]
    assert [r["email"] for r in mgr] == ["cust@a.com"] and mgr[0]["orders"] == 1 and mgr[0]["spent"] == "30.00"  # only own-branch activity
    assert [r["email"] for r in api(world, "admin_a").get("/api/v1/customers/directory/", {"q": "cust2"}).json()["data"]["results"]] == ["cust2@a.com"]


def test_directory_is_manager_only_and_tenant_isolated(world, shop, clean):  # noqa: F811
    for who in ("cashier_a1", "kitchen_a1", "cust_a", "delivery_a1"):
        assert api(world, who).get("/api/v1/customers/directory/").status_code == 403
    assert api(world, "admin_b", "bravo").get("/api/v1/customers/directory/").json()["data"]["results"] == []
    assert api(world, "admin_b", "bravo").get(f"/api/v1/customers/directory/{world['cust_a'].pk}/").status_code == 404
    mk_order(world, world["a2"], "20.00", customer=world["cust2_a"], paid="20.00")
    assert api(world, "mgr_a1").get(f"/api/v1/customers/directory/{world['cust2_a'].pk}/").status_code == 404  # never ordered at a1


def test_directory_detail_notes_and_audit(world, shop, clean):  # noqa: F811
    mk_order(world, world["a1"], "30.00", customer=world["cust_a"], paid="30.00")
    m = api(world, "mgr_a1")
    url = f"/api/v1/customers/directory/{world['cust_a'].pk}/"
    assert m.post(url, {"text": "Allergic to peanuts"}, format="json").status_code == 201
    assert m.post(url, {"text": " "}, format="json").status_code == 400
    d = m.get(url).json()["data"]
    assert d["notes"][0]["text"] == "Allergic to peanuts" and d["recent_orders"][0]["total"] == "30.00" and d["orders"] == 1
    assert AuditLog.objects.filter(action="customer.viewed").exists() and AuditLog.objects.filter(action="customer.note_added").exists()
    n = CustomerNote.unscoped.get()
    with pytest.raises(PermissionError):
        n.delete()
    n.text = "x"
    with pytest.raises(PermissionError):
        n.save()
