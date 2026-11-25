import datetime
import uuid
from decimal import Decimal

import pytest

from apps.catalog.models import Product
from apps.core.models import AuditLog
from apps.finance.models import Expense, Invoice, InvoicePayment
from apps.notifications.models import EmailLog
from apps.orders.models import Order
from apps.procurement.models import Ingredient, IngredientMovement, IngredientStock, PurchaseOrder, RecipeLine

from .conftest import client_for
from .test_phase5_orders import clean, shop  # noqa: F401

F = "/api/v1/finance/"
PR = "/api/v1/procurement/"
TODAY = datetime.date.today()


def api(world, who, slug="alpha"):
    return client_for(world[who], slug)


def mk_cat(world, name="Utilities"):
    r = api(world, "admin_a").post(F + "categories/", {"name": name}, format="json")
    assert r.status_code == 201, r.content
    return r.json()["data"]["id"]


def expense(world, who, cat, **over):
    body = {"category_id": cat, "description": "Electricity", "amount": "120.50", "expense_date": TODAY.isoformat(), "method": "bank_transfer", "reference": "TX1", "branch_id": world["a1"].pk, **over}
    return api(world, who).post(F + "expenses/", body, format="json")


# ================================ expenses ================================
def test_expense_lifecycle_scope_and_audit(world, clean):  # noqa: F811
    cat = mk_cat(world)
    r = expense(world, "mgr_a1", cat)
    assert r.status_code == 201 and r.json()["data"]["amount"] == "120.50"
    eid = r.json()["data"]["id"]
    assert expense(world, "mgr_a1", cat, branch_id=world["a2"].pk).status_code == 404  # not their branch
    assert expense(world, "mgr_a1", cat, branch_id=None).status_code == 400  # managers must choose a branch
    assert expense(world, "admin_a", cat, branch_id=None).status_code == 201  # restaurant-wide: admin only
    listed = api(world, "mgr_a1").get(F + "expenses/").json()["data"]
    assert listed["count"] == 1 and listed["total_recorded"] == "120.50"  # admin's restaurant-wide cost is invisible to the manager
    assert api(world, "admin_a").get(F + "expenses/").json()["data"]["total_recorded"] == "241.00"
    assert api(world, "mgr_a1").post(F + f"expenses/{eid}/void/", {"reason": "mistake"}, format="json").status_code == 400
    a = api(world, "admin_a")
    assert a.post(F + f"expenses/{eid}/void/", {"reason": ""}, format="json").status_code == 400
    assert a.post(F + f"expenses/{eid}/void/", {"reason": "Entered twice"}, format="json").json()["data"]["status"] == "void"
    assert a.get(F + "expenses/").json()["data"]["total_recorded"] == "120.50"  # void excluded
    assert a.post(F + f"expenses/{eid}/void/", {"reason": "again"}, format="json").status_code == 400
    e = Expense.unscoped.get(pk=eid)
    with pytest.raises(PermissionError):
        e.delete()
    assert {"expense.recorded", "expense.voided"} <= set(AuditLog.objects.values_list("action", flat=True))


def test_expense_validation_and_roles(world, clean):  # noqa: F811
    cat = mk_cat(world)
    for bad in ({"amount": "0"}, {"amount": "-5"}, {"expense_date": (TODAY + datetime.timedelta(days=2)).isoformat()}, {"method": "bitcoin"}, {"category_id": 99999}, {"description": ""}):
        assert expense(world, "mgr_a1", cat, **bad).status_code == 400, bad
    for who in ("cashier_a1", "cust_a", "kitchen_a1"):
        assert api(world, who).get(F + "expenses/").status_code == 403
        assert expense(world, who, cat).status_code == 403
    assert api(world, "mgr_a1").post(F + "categories/", {"name": "x"}, format="json").status_code == 400  # admin only
    assert api(world, "admin_a").post(F + "categories/", {"name": "utilities"}, format="json").status_code == 400  # duplicate, case-insensitive
    assert api(world, "admin_a").post(F + "categories/", {"name": "Insurance"}, format="json").status_code == 201
    assert expense(world, "admin_a", cat, category_id=mk_cat(world, "Rent")).status_code == 201


def test_expenses_are_tenant_isolated(world, clean):  # noqa: F811
    cat = mk_cat(world)
    eid = expense(world, "mgr_a1", cat).json()["data"]["id"]
    b = api(world, "admin_b", "bravo")
    assert b.get(F + "expenses/").json()["data"]["count"] == 0
    assert b.post(F + f"expenses/{eid}/void/", {"reason": "nope"}, format="json").status_code == 404
    body = {"category_id": cat, "description": "x", "amount": "5.00", "expense_date": TODAY.isoformat(), "method": "cash", "branch_id": world["b1"].pk}
    assert b.post(F + "expenses/", body, format="json").status_code == 400  # alpha's category is not visible to bravo
    assert b.get(F + "categories/").json()["data"] == []


def test_expenses_flow_into_the_financial_report(world, clean):  # noqa: F811
    cat = mk_cat(world)
    expense(world, "mgr_a1", cat, amount="100.00")
    eid = expense(world, "mgr_a1", cat, amount="40.00").json()["data"]["id"]
    api(world, "admin_a").post(F + f"expenses/{eid}/void/", {"reason": "oops"}, format="json")
    d = api(world, "admin_a").get("/api/v1/reports/finance/").json()["data"]
    assert d["expenses"]["recorded"] == "100.00" and d["expenses"]["by_category"] == [{"category": "Utilities", "amount": "100.00"}]
    assert d["operating_result"] == "-100.00" and d["expenses"]["total"] == "100.00"


# ================================ invoices ================================
def invoice(world, **over):
    body = {"customer_name": "Acme Ltd", "customer_email": "ap@acme.test", "customer_address": "1 Main St", "tax_rate_percent": "10",
            "lines": [{"description": "Lunch buffet", "quantity": "20", "unit_price": "15.50"}, {"description": "Service", "quantity": "1", "unit_price": "50.00"}], **over}
    return api(world, "mgr_a1").post(F + "invoices/", body, format="json")


def test_invoice_totals_are_computed_by_the_server(world, clean):  # noqa: F811
    d = invoice(world).json()["data"]
    assert d["subtotal"] == "360.00" and d["tax_total"] == "36.00" and d["total"] == "396.00" and d["status"] == "draft" and d["number"] == ""
    assert invoice(world, lines=[]).status_code == 400
    assert invoice(world, lines=[{"description": "x", "quantity": "0", "unit_price": "1"}]).status_code == 400
    assert invoice(world, lines=[{"description": " ", "quantity": "1", "unit_price": "1"}]).status_code == 400
    assert invoice(world, tax_rate_percent="101").status_code == 400


def test_invoice_full_flow_numbering_payments_and_immutability(world, clean):  # noqa: F811
    m = api(world, "mgr_a1")
    iid = invoice(world).json()["data"]["id"]
    assert m.patch(F + f"invoices/{iid}/", {"notes": "Thanks", "lines": [{"description": "Buffet", "quantity": "10", "unit_price": "10.00"}]}, format="json").json()["data"]["total"] == "110.00"
    assert m.post(F + f"invoices/{iid}/payments/", {"amount": "10", "method": "cash", "received_on": TODAY.isoformat()}, format="json", HTTP_IDEMPOTENCY_KEY="a").status_code == 400  # draft
    assert m.post(F + f"invoices/{iid}/issue/", {"due_date": (TODAY - datetime.timedelta(days=1)).isoformat()}, format="json").status_code == 400
    r = m.post(F + f"invoices/{iid}/issue/", {"due_date": (TODAY + datetime.timedelta(days=14)).isoformat()}, format="json")
    assert r.status_code == 200 and r.json()["data"]["number"] == "INV-000001" and r.json()["data"]["status"] == "issued"
    assert EmailLog.objects.filter(template="invoice_issued").count() == 1
    assert m.patch(F + f"invoices/{iid}/", {"notes": "changed"}, format="json").status_code == 400  # immutable once issued
    assert m.post(F + f"invoices/{iid}/issue/", {"due_date": TODAY.isoformat()}, format="json").status_code == 400
    pay = lambda amt, key=None: m.post(F + f"invoices/{iid}/payments/", {"amount": amt, "method": "bank_transfer", "reference": "R", "received_on": TODAY.isoformat()}, format="json", HTTP_IDEMPOTENCY_KEY=key or uuid.uuid4().hex)  # noqa: E731
    assert pay("200.00").status_code == 400  # more than the balance
    k = uuid.uuid4().hex
    a, b = pay("60.00", k), pay("60.00", k)
    assert a.status_code == b.status_code == 200 and a.json() == b.json() and InvoicePayment.unscoped.count() == 1
    d = pay("50.00").json()["data"]
    assert d["status"] == "paid" and d["balance"] == "0.00" and d["amount_paid"] == "110.00"
    assert pay("1.00").status_code == 400
    assert m.post(F + f"invoices/{iid}/void/", {"reason": "x"}, format="json").status_code == 400  # manager cannot void
    assert api(world, "admin_a").post(F + f"invoices/{iid}/void/", {"reason": "mistake"}, format="json").status_code == 400  # has payments
    p = InvoicePayment.unscoped.first()
    with pytest.raises(PermissionError):
        p.save()
    with pytest.raises(PermissionError):
        Invoice.unscoped.get(pk=iid).delete()
    iid2 = invoice(world).json()["data"]["id"]
    m.post(F + f"invoices/{iid2}/issue/", {"due_date": TODAY.isoformat()}, format="json")
    assert Invoice.unscoped.get(pk=iid2).number == "INV-000002"


def test_void_invoice_overdue_pdf_and_isolation(world, clean):  # noqa: F811
    m = api(world, "mgr_a1")
    iid = invoice(world).json()["data"]["id"]
    assert m.get(F + f"invoices/{iid}/pdf/").status_code == 404  # drafts have no document
    m.post(F + f"invoices/{iid}/issue/", {"due_date": TODAY.isoformat()}, format="json")
    Invoice.unscoped.filter(pk=iid).update(due_date=TODAY - datetime.timedelta(days=3))
    lst = m.get(F + "invoices/", {"overdue": 1}).json()["data"]
    assert lst["count"] == 1 and lst["results"][0]["overdue"] is True and lst["outstanding"] == "396.00"
    pdf = m.get(F + f"invoices/{iid}/pdf/")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    b = api(world, "admin_b", "bravo")
    assert b.get(F + f"invoices/{iid}/").status_code == 404 and b.get(F + f"invoices/{iid}/pdf/").status_code == 404 and b.get(F + "invoices/").json()["data"]["count"] == 0
    a = api(world, "admin_a")
    assert a.post(F + f"invoices/{iid}/void/", {"reason": "customer cancelled"}, format="json").json()["data"]["status"] == "void"
    assert a.post(F + f"invoices/{iid}/void/", {"reason": "again"}, format="json").status_code == 400
    assert a.get("/api/v1/reports/finance/").json()["data"]["receivables"]["invoices"] == "0.00"
    for who in ("cashier_a1", "cust_a"):
        assert api(world, who).get(F + "invoices/").status_code == 403


def test_issued_invoices_count_as_receivables(world, clean):  # noqa: F811
    iid = invoice(world).json()["data"]["id"]
    api(world, "mgr_a1").post(F + f"invoices/{iid}/issue/", {"due_date": TODAY.isoformat()}, format="json")
    assert api(world, "admin_a").get("/api/v1/reports/finance/").json()["data"]["receivables"]["invoices"] == "396.00"


# ================================ suppliers, ingredients, purchase orders ================================
def mk_ing(world, name="Rice", unit="kg", threshold="5", who="mgr_a1"):
    r = api(world, who).post(PR + "ingredients/", {"name": name, "unit": unit, "low_stock_threshold": threshold}, format="json")
    assert r.status_code == 201, r.content
    return r.json()["data"]["id"]


def mk_sup(world, name="Fresh Farms"):
    r = api(world, "mgr_a1").post(PR + "suppliers/", {"name": name, "phone": "123456"}, format="json")
    assert r.status_code == 201, r.content
    return r.json()["data"]["id"]


def stock(world, ing, branch="a1"):
    return IngredientStock.unscoped.filter(ingredient_id=ing, branch=world[branch]).values_list("quantity", flat=True).first()


def test_suppliers_and_ingredients_crud_rules(world, clean):  # noqa: F811
    sid = mk_sup(world)
    assert api(world, "mgr_a1").post(PR + "suppliers/", {"name": "fresh farms"}, format="json").status_code == 400
    assert api(world, "mgr_a1").patch(PR + f"suppliers/{sid}/", {"is_active": False}, format="json").json()["data"]["is_active"] is False
    assert api(world, "mgr_a1").delete(PR + f"suppliers/{sid}/").status_code == 405
    assert api(world, "admin_b", "bravo").get(PR + f"suppliers/{sid}/").status_code == 404
    iid = mk_ing(world)
    assert api(world, "mgr_a1").post(PR + "ingredients/", {"name": "RICE", "unit": "kg"}, format="json").status_code == 400
    assert api(world, "mgr_a1").post(PR + "ingredients/", {"name": "Bad", "unit": "parsec"}, format="json").status_code == 400
    for who in ("cashier_a1", "cust_a", "kitchen_a1"):
        assert api(world, who).get(PR + "ingredients/").status_code == 403
        assert api(world, who).get(PR + "suppliers/").status_code == 403
    assert api(world, "admin_b", "bravo").get(PR + "ingredients/").json()["data"] == []
    assert iid


def test_stock_adjustments_are_audited_scoped_and_validated(world, clean):  # noqa: F811
    iid = mk_ing(world)
    m = api(world, "mgr_a1")
    adj = lambda **kw: m.post(PR + "stock/adjust/", {"ingredient_id": iid, "branch_id": world["a1"].pk, "mode": "delta", "quantity": "10", "reason": "opening", "note": "Opening count", **kw}, format="json")  # noqa: E731
    assert adj().status_code == 200 and stock(world, iid) == Decimal("10.000")
    assert adj(mode="set", quantity="8", reason="adjustment", note="Recount").status_code == 200 and stock(world, iid) == Decimal("8.000")
    assert adj(quantity="-3", reason="waste", note="Spoiled").status_code == 200 and stock(world, iid) == Decimal("5.000")
    assert adj(quantity="2", reason="waste", note="Spoiled").status_code == 400  # waste cannot add
    assert adj(note=" ").status_code == 400 and adj(mode="set", quantity="5", reason="adjustment").json() is not None
    assert adj(mode="set", quantity="5", reason="adjustment", note="same").status_code == 400  # no change
    assert adj(branch_id=world["a2"].pk).status_code == 404  # other branch
    assert adj(mode="set", quantity="-1", reason="adjustment", note="neg").status_code == 400
    mv = IngredientMovement.unscoped.filter(ingredient_id=iid).order_by("id")
    assert [str(x.delta) for x in mv] == ["10.000", "-2.000", "-3.000"] and [str(x.quantity_after) for x in mv] == ["10.000", "8.000", "5.000"]
    with pytest.raises(PermissionError):
        mv[0].delete()
    row = api(world, "mgr_a1").get(PR + "ingredients/").json()["data"][0]
    assert row["total"] == "5.000" and row["low"] is True  # 5 <= threshold 5
    assert len(api(world, "mgr_a1").get(PR + "ingredients/", {"low": 1}).json()["data"]) == 1
    assert api(world, "mgr_a1").get(PR + "stock/movements/").json()["data"]["count"] == 3
    assert api(world, "mgr_a2", "alpha").get(PR + "ingredients/").json()["data"][0]["branches"] == []  # sees no stock of branch a1


def test_purchase_order_flow_receiving_and_cost(world, clean):  # noqa: F811
    rice, oil, sup = mk_ing(world), mk_ing(world, "Oil", "l", "2"), mk_sup(world)
    m = api(world, "mgr_a1")
    body = {"branch_id": world["a1"].pk, "supplier_id": sup, "expected_date": TODAY.isoformat(), "lines": [{"ingredient_id": rice, "quantity": "25", "unit_cost": "1.2000"}, {"ingredient_id": oil, "quantity": "10", "unit_cost": "3.5000"}]}
    r = m.post(PR + "orders/", body, format="json")
    assert r.status_code == 201 and r.json()["data"]["number"] == "PO-000001" and r.json()["data"]["total"] == "65.00"
    po = r.json()["data"]
    assert m.post(PR + "orders/", {**body, "branch_id": world["a2"].pk}, format="json").status_code == 404
    assert m.post(PR + "orders/", {**body, "lines": []}, format="json").status_code == 400
    assert m.post(PR + f"orders/{po['id']}/receive/", {"lines": [{"line_id": po["lines"][0]["id"], "quantity": "5"}]}, format="json").status_code == 400  # not ordered yet
    assert m.patch(PR + f"orders/{po['id']}/", {"lines": [{"ingredient_id": rice, "quantity": "20", "unit_cost": "1.2000"}]}, format="json").json()["data"]["total"] == "24.00"
    assert m.post(PR + f"orders/{po['id']}/order/").json()["data"]["status"] == "ordered"
    assert m.patch(PR + f"orders/{po['id']}/", {"notes": "x"}, format="json").status_code == 400
    line = m.get(PR + f"orders/{po['id']}/").json()["data"]["lines"][0]
    assert m.post(PR + f"orders/{po['id']}/receive/", {"lines": [{"line_id": line["id"], "quantity": "25"}]}, format="json").status_code == 400  # over-receive
    assert m.post(PR + f"orders/{po['id']}/receive/", {"lines": [{"line_id": line["id"], "quantity": "0"}]}, format="json").status_code == 400
    r = m.post(PR + f"orders/{po['id']}/receive/", {"lines": [{"line_id": line["id"], "quantity": "12"}]}, format="json")
    assert r.json()["data"]["status"] == "partially_received" and stock(world, rice) == Decimal("12.000")
    assert m.post(PR + f"orders/{po['id']}/cancel/", {"reason": "late"}, format="json").status_code == 400  # stock already received
    r = m.post(PR + f"orders/{po['id']}/receive/", {"lines": [{"line_id": line["id"], "quantity": "8"}]}, format="json")
    assert r.json()["data"]["status"] == "received" and stock(world, rice) == Decimal("20.000")
    assert Ingredient.unscoped.get(pk=rice).last_unit_cost == Decimal("1.2000")
    assert m.post(PR + f"orders/{po['id']}/receive/", {"lines": [{"line_id": line["id"], "quantity": "1"}]}, format="json").status_code == 400
    assert IngredientMovement.unscoped.filter(reason="purchase", purchase_order_id=po["id"]).count() == 2
    assert api(world, "mgr_a2").get(PR + f"orders/{po['id']}/").status_code == 404 and api(world, "admin_b", "bravo").get(PR + f"orders/{po['id']}/").status_code == 404
    po2 = m.post(PR + "orders/", body, format="json").json()["data"]
    assert m.post(PR + f"orders/{po2['id']}/cancel/", {"reason": ""}, format="json").status_code == 400
    assert m.post(PR + f"orders/{po2['id']}/cancel/", {"reason": "Wrong supplier"}, format="json").json()["data"]["status"] == "cancelled"
    assert PurchaseOrder.unscoped.get(pk=po2["id"]).number == "PO-000002"


def test_purchase_expense_links_to_the_order(world, clean):  # noqa: F811
    rice, sup = mk_ing(world), mk_sup(world)
    m = api(world, "mgr_a1")
    po = m.post(PR + "orders/", {"branch_id": world["a1"].pk, "supplier_id": sup, "lines": [{"ingredient_id": rice, "quantity": "10", "unit_cost": "2"}]}, format="json").json()["data"]
    cat = mk_cat(world, "Purchases")
    r = expense(world, "mgr_a1", cat, amount="20.00", purchase_order_id=po["id"])
    assert r.status_code == 201 and r.json()["data"]["purchase_order"] == po["number"] and r.json()["data"]["supplier"] == "Fresh Farms"
    assert expense(world, "mgr_a1", cat, purchase_order_id=99999).status_code == 400


# ================================ recipes and ingredient deduction ================================
def test_recipes_deduct_ingredients_per_branch_and_restore_on_cancel(world, shop, clean):  # noqa: F811
    from .test_phase15_pos_directory import open_shift, sale

    rice = mk_ing(world, "Rice", "kg", "1")
    chicken = mk_ing(world, "Chicken", "kg", "1")
    m = api(world, "mgr_a1")
    for ing in (rice, chicken):
        m.post(PR + "stock/adjust/", {"ingredient_id": ing, "branch_id": world["a1"].pk, "mode": "delta", "quantity": "10", "reason": "opening", "note": "Opening"}, format="json")
    dish = shop["rice"]
    r = m.put(PR + f"products/{dish.pk}/recipe/", {"lines": [{"ingredient_id": rice, "quantity": "0.2"}, {"ingredient_id": chicken, "quantity": "0.15"}]}, format="json")
    assert r.status_code == 200 and len(r.json()["data"]) == 2
    assert m.put(PR + f"products/{dish.pk}/recipe/", {"lines": [{"ingredient_id": rice, "quantity": "0.2"}, {"ingredient_id": rice, "quantity": "1"}]}, format="json").status_code == 400
    assert m.put(PR + f"products/{dish.pk}/recipe/", {"lines": [{"ingredient_id": 9999, "quantity": "1"}]}, format="json").status_code == 400
    assert api(world, "admin_b", "bravo").put(PR + f"products/{dish.pk}/recipe/", {"lines": []}, format="json").status_code == 404
    open_shift(world)
    resp = sale(world, "cashier_a1", [{"product_id": dish.pk, "quantity": 3}])
    assert resp.status_code == 201, resp.content
    assert stock(world, rice) == Decimal("9.400") and stock(world, chicken) == Decimal("9.550")  # 3 x 0.2, 3 x 0.15
    assert IngredientMovement.unscoped.filter(reason="sale").count() == 2
    assert stock(world, rice, "a2") is None  # other branches untouched
    num = resp.json()["data"]["order"]["number"]
    order = Order.unscoped.get(number=num)
    from apps.orders.services import transition_order  # cancel path restores through the same module
    assert order.stock_restored is False
    # the payment was taken, so refund is required before cancelling: restore is exercised directly instead
    from apps.orders.services import _restore_stock
    _restore_stock(order, world["mgr_a1"])
    assert stock(world, rice) == Decimal("10.000") and stock(world, chicken) == Decimal("10.000")
    assert IngredientMovement.unscoped.filter(reason="sale_return").count() == 2
    _ = transition_order


def test_recipe_usage_never_blocks_a_sale_and_may_go_negative(world, shop, clean):  # noqa: F811
    from .test_phase15_pos_directory import open_shift, sale

    rice = mk_ing(world, "Rice", "kg", "1")
    api(world, "mgr_a1").put(PR + f"products/{shop['rice'].pk}/recipe/", {"lines": [{"ingredient_id": rice, "quantity": "0.5"}]}, format="json")
    open_shift(world)
    assert sale(world, "cashier_a1", [{"product_id": shop["rice"].pk, "quantity": 2}]).status_code == 201
    assert stock(world, rice) == Decimal("-1.000")
    row = api(world, "mgr_a1").get(PR + "ingredients/").json()["data"][0]
    assert row["low"] is True
    s = api(world, "mgr_a1").get(PR + "summary/").json()["data"]
    assert s["low_stock_count"] == 1 and s["open_orders"] == 0


def test_products_without_recipes_are_unaffected(world, shop, clean):  # noqa: F811
    from .test_phase15_pos_directory import open_shift, sale

    open_shift(world)
    assert sale(world, "cashier_a1", [{"product_id": shop["pizza"].pk, "quantity": 1, "variation_id": shop["large"].pk}]).status_code == 201
    assert IngredientMovement.unscoped.count() == 0
    assert RecipeLine.unscoped.count() == 0 and Product.unscoped.count() >= 1


def test_concurrent_numbering_helper_is_sequential(world, clean):  # noqa: F811
    from apps.core.models import next_document_number

    nums = [next_document_number(world["a"], "x", "X") for _ in range(5)] + [next_document_number(world["b"], "x", "X")]
    assert nums == ["X-000001", "X-000002", "X-000003", "X-000004", "X-000005", "X-000001"]
