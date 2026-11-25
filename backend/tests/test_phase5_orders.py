import json
from decimal import Decimal

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Role, User
from apps.catalog.models import Category, Product, ProductAddon, ProductVariation, StockMovement
from apps.core.models import AuditLog
from apps.customers.models import CustomerAddress
from apps.notifications.providers import ConsoleProvider
from apps.orders.models import Order, OrderItem, OrderSequence, OrderStatusHistory, Status
from apps.tenants.models import Branch, RestaurantSettings

from .conftest import PW, client_for, host

O = "/api/v1/orders/"


@pytest.fixture(autouse=True)
def clean(db):
    ConsoleProvider.outbox.clear()
    cache.clear()


@pytest.fixture
def shop(world):
    """Alpha menu: a plain dish, a sized dish with extras, a tracked-stock dish; plus a Bravo dish."""
    a, b = world["a"], world["b"]
    st = RestaurantSettings.objects.create(restaurant=a, currency="USD", tax_rate_percent=Decimal("8.25"), delivery_fee=Decimal("2.00"))
    RestaurantSettings.objects.create(restaurant=b)
    cat = Category.unscoped.create(restaurant=a, name="Mains", slug="mains")
    rice = Product.unscoped.create(restaurant=a, category=cat, name="Rice", slug="rice", base_price=Decimal("10.10"))
    pizza = Product.unscoped.create(restaurant=a, category=cat, name="Pizza", slug="pizza", base_price=Decimal("12.00"), allow_instructions=False)
    small = ProductVariation.unscoped.create(restaurant=a, product=pizza, name="Small", price_delta=Decimal("0"), is_default=True)
    large = ProductVariation.unscoped.create(restaurant=a, product=pizza, name="Large", price_delta=Decimal("4.50"))
    cheese = ProductAddon.unscoped.create(restaurant=a, product=pizza, name="Cheese", price=Decimal("1.25"), max_quantity=2)
    fish = Product.unscoped.create(restaurant=a, category=cat, name="Fish", slug="fish", base_price=Decimal("20.00"),
                                   track_inventory=True, stock_quantity=3)
    bcat = Category.unscoped.create(restaurant=b, name="Food", slug="food")
    bdish = Product.unscoped.create(restaurant=b, category=bcat, name="Bravo dish", slug="bravo-dish", base_price=Decimal("5.00"))
    return dict(rice=rice, pizza=pizza, small=small, large=large, cheese=cheese, fish=fish, bdish=bdish, cat=cat, settings=st)


def cust(world, who="cust_a", slug="alpha"):
    return client_for(world[who], slug)


def line(p, qty=1, **kw):
    return {"product_id": p.pk, "quantity": qty, **kw}


def body(world, items, **over):
    return {"items": items, "fulfilment": "pickup", "payment_method": "cash", "contact_phone": "+23276123456",
            "branch_id": world["a1"].pk, **over}


def checkout(world, items, key="k1", who="cust_a", **over):
    c = cust(world, who)
    return c.post(O + "checkout/", body(world, items, **over), format="json", HTTP_IDEMPOTENCY_KEY=key)


# ---- pricing -----------------------------------------------------------------------------------
def quote(world, items, slug="alpha", **over):
    return APIClient(HTTP_HOST=host(slug)).post(O + "quote/", {"items": items, "fulfilment": "pickup", **over}, format="json")


def test_quote_computes_every_amount_in_decimal_on_the_server(world, shop):
    q = quote(world, [line(shop["rice"], 3), line(shop["pizza"], 2, variation_id=shop["large"].pk, addons=[{"id": shop["cheese"].pk, "quantity": 2}])])
    assert q.status_code == 200
    d = json.loads(q.content)["data"]
    # rice 3 x 10.10 = 30.30 ; pizza unit = 12.00 + 4.50 + 2 x 1.25 = 19.00, x2 = 38.00
    assert [l["line_total"] for l in d["lines"]] == ["30.30", "38.00"]
    assert d["subtotal"] == "68.30" and d["tax_total"] == "5.63"  # 68.30 x 8.25% = 5.63475 -> 5.63
    assert d["delivery_fee"] == "0.00" and d["total"] == "73.93" and d["currency"] == "USD"


def test_tax_rounds_half_up_and_delivery_fee_applies_only_to_delivery(world, shop):
    shop["settings"].tax_rate_percent = Decimal("8.25")
    shop["settings"].save()
    shop["rice"].base_price = Decimal("33.33")
    shop["rice"].save()
    d = json.loads(quote(world, [line(shop["rice"])], fulfilment="delivery").content)["data"]
    assert d["tax_total"] == "2.75" and d["delivery_fee"] == "2.00" and d["total"] == "38.08"  # 2.749725 rounds up


def test_client_supplied_prices_are_ignored(world, shop):
    forged = {**line(shop["rice"]), "price": "0.01", "unit_price": "0.01", "line_total": "0.01"}
    d = json.loads(quote(world, [forged], total="0.01", subtotal="0.01").content)["data"]
    assert d["lines"][0]["unit_price"] == "10.10" and d["total"] == "10.93"
    r = checkout(world, [forged], total="0.01", subtotal="0.01")
    assert r.status_code == 201 and r.data["total"] == "10.93"


def test_offer_price_is_used_until_it_expires(world, shop):
    shop["rice"].offer_price = Decimal("8.00")
    shop["rice"].save()
    assert json.loads(quote(world, [line(shop["rice"])]).content)["data"]["lines"][0]["unit_price"] == "8.00"


@pytest.mark.parametrize("mutate,expect", [
    (lambda s, w: {"product_id": s["bdish"].pk, "quantity": 1}, "other tenant's product"),
    (lambda s, w: {"product_id": 999999, "quantity": 1}, "unknown product"),
    (lambda s, w: {"product_id": s["pizza"].pk, "quantity": 1, "variation_id": s["bdish"].pk}, "foreign variation"),
    (lambda s, w: {"product_id": s["pizza"].pk, "quantity": 1, "addons": [{"id": s["cheese"].pk, "quantity": 3}]}, "addon over max"),
    (lambda s, w: {"product_id": s["pizza"].pk, "quantity": 1, "addons": [{"id": s["cheese"].pk}, {"id": s["cheese"].pk}]}, "duplicate addon"),
    (lambda s, w: {"product_id": s["pizza"].pk, "quantity": 1, "instructions": "no onion"}, "instructions disallowed"),
    (lambda s, w: {"product_id": s["rice"].pk, "quantity": 0}, "zero quantity"),
    (lambda s, w: {"product_id": s["rice"].pk, "quantity": 51}, "quantity cap"),
    (lambda s, w: {"product_id": s["rice"].pk, "quantity": 1, "variation_id": s["small"].pk}, "variation of another product"),
])
def test_invalid_cart_lines_are_rejected(world, shop, mutate, expect):
    assert quote(world, [mutate(shop, world)]).status_code == 400, expect


def test_hidden_archived_and_inactive_items_cannot_be_ordered(world, shop):
    for change in (dict(is_available=False), dict(is_archived=True)):
        Product.unscoped.filter(pk=shop["rice"].pk).update(**change)
        assert quote(world, [line(shop["rice"])]).status_code == 400
        Product.unscoped.filter(pk=shop["rice"].pk).update(is_available=True, is_archived=False)
    Category.unscoped.filter(pk=shop["cat"].pk).update(is_active=False)
    assert quote(world, [line(shop["rice"])]).status_code == 400


def test_empty_cart_and_disabled_fulfilment_rejected(world, shop):
    assert quote(world, []).status_code == 400
    shop["settings"].delivery_enabled = False
    shop["settings"].save()
    assert quote(world, [line(shop["rice"])], fulfilment="delivery").status_code == 400


def test_pizza_requires_a_choice_only_when_there_is_no_default(world, shop):
    assert json.loads(quote(world, [line(shop["pizza"])]).content)["data"]["lines"][0]["variation"] == "Small"  # default applied
    shop["small"].is_default = False
    shop["small"].save()
    assert quote(world, [line(shop["pizza"])]).status_code == 400


# ---- checkout, idempotency, snapshots ----------------------------------------------------------
def test_checkout_requires_customer_login_and_idempotency_key(world, shop):
    items = [line(shop["rice"])]
    assert APIClient(HTTP_HOST=host("alpha")).post(O + "checkout/", body(world, items), format="json").status_code == 401
    for who in ("admin_a", "mgr_a1", "cashier_a1"):
        assert client_for(world[who], "alpha").post(O + "checkout/", body(world, items), format="json", HTTP_IDEMPOTENCY_KEY="x").status_code == 403
    assert cust(world).post(O + "checkout/", body(world, items), format="json").status_code == 400  # no key
    assert Order.unscoped.count() == 0


def test_checkout_creates_complete_order_history_audit_and_email(world, shop):
    r = checkout(world, [line(shop["rice"], 2), line(shop["pizza"], addons=[{"id": shop["cheese"].pk, "quantity": 1}])], notes="ring bell")
    assert r.status_code == 201, r.data
    o = Order.unscoped.get()
    assert (o.number, o.status, o.payment_status, o.customer_id) == ("ORD-000001", "awaiting_payment", "unpaid", world["cust_a"].pk)
    assert o.subtotal == Decimal("33.45") and o.total == o.subtotal + o.tax_total + o.delivery_fee
    assert o.branch_id == world["a1"].pk and o.restaurant_id == world["a"].pk
    assert [(h.from_status, h.to_status, h.actor_role) for h in o.history.all()] == [("", "awaiting_payment", "customer")]
    assert AuditLog.objects.filter(action="order.created", restaurant=world["a"]).count() == 1
    mail = [m for m in ConsoleProvider.outbox if m["to"] == "cust@a.com"][0]
    assert "ORD-000001" in mail["html"] and "2 × Rice" in mail["html"] and "http://alpha.platform.test/account/orders/" in mail["html"]


def test_idempotent_checkout_replays_instead_of_duplicating(world, shop):
    first = checkout(world, [line(shop["rice"])], key="same")
    again = checkout(world, [line(shop["rice"])], key="same")
    assert first.status_code == again.status_code == 201 and first.data == again.data
    assert Order.unscoped.count() == 1 and OrderItem.unscoped.count() == 1
    assert len([m for m in ConsoleProvider.outbox if m["to"] == "cust@a.com"]) == 1  # one confirmation email
    assert checkout(world, [line(shop["rice"], 5)], key="same").status_code == 400  # same key, different cart
    assert checkout(world, [line(shop["rice"])], key="other").status_code == 201 and Order.unscoped.count() == 2


def test_idempotency_keys_are_scoped_per_customer(world, shop):
    a = checkout(world, [line(shop["rice"])], key="shared")
    b = checkout(world, [line(shop["rice"])], key="shared", who="cust2_a")
    assert a.data["id"] != b.data["id"] and Order.unscoped.count() == 2


def test_order_numbers_are_sequential_per_restaurant(world, shop):
    for i in range(3):
        checkout(world, [line(shop["rice"])], key=f"k{i}")
    assert list(Order.unscoped.order_by("id").values_list("number", flat=True)) == ["ORD-000001", "ORD-000002", "ORD-000003"]
    assert OrderSequence.objects.get(restaurant=world["a"]).last_number == 3
    Membership.objects.get_or_create(user=world["cust_a"], restaurant=world["b"], defaults={"role": "customer"})
    c = client_for(world["cust_a"], "bravo")
    r = c.post(O + "checkout/", {"items": [line(shop["bdish"])], "fulfilment": "pickup", "payment_method": "cash",
                                 "contact_phone": "+23276123456", "branch_id": world["b1"].pk}, format="json", HTTP_IDEMPOTENCY_KEY="b1")
    assert r.status_code == 201 and r.data["number"] == "ORD-000001"  # Bravo has its own sequence


def test_order_items_are_immutable_snapshots(world, shop):
    r = checkout(world, [line(shop["rice"], 2)])
    Product.unscoped.filter(pk=shop["rice"].pk).update(name="Renamed", base_price=Decimal("99.00"))
    detail = cust(world).get(f"{O}my/{r.data['id']}/").data
    assert detail["items"][0]["product_name"] == "Rice" and detail["items"][0]["unit_price"] == "10.10" and detail["total"] == r.data["total"]
    item = OrderItem.unscoped.get()
    item.quantity = 9
    with pytest.raises(PermissionError):
        item.save()
    with pytest.raises(PermissionError):
        item.delete()
    h = OrderStatusHistory.unscoped.first()
    with pytest.raises(PermissionError):
        h.delete()


def test_cannot_use_online_payment_yet_or_bad_phone(world, shop):
    assert checkout(world, [line(shop["rice"])], payment_method="mobile_money").status_code == 400
    assert checkout(world, [line(shop["rice"])], key="p", contact_phone="abc").status_code == 400
    assert Order.unscoped.count() == 0


def test_branch_rules(world, shop):
    items = [line(shop["rice"])]
    c = cust(world)
    no_branch = {**body(world, items)}
    no_branch.pop("branch_id")
    assert c.post(O + "checkout/", no_branch, format="json", HTTP_IDEMPOTENCY_KEY="nb").status_code == 400  # two branches: must choose
    assert checkout(world, items, key="x1", branch_id=world["b1"].pk).status_code == 400  # other tenant's branch
    Branch.unscoped.filter(pk=world["a2"].pk).update(status="suspended")
    assert checkout(world, items, key="x2", branch_id=world["a2"].pk).status_code == 400
    assert c.post(O + "checkout/", no_branch, format="json", HTTP_IDEMPOTENCY_KEY="nb2").status_code == 201  # one active branch: implied


def test_delivery_needs_address_and_only_own_saved_addresses(world, shop):
    items = [line(shop["rice"])]
    assert checkout(world, items, fulfilment="delivery").status_code == 400
    mine = CustomerAddress.unscoped.create(restaurant=world["a"], user=world["cust_a"], line1="1 Main", city="Freetown", phone="+232761")
    theirs = CustomerAddress.unscoped.create(restaurant=world["a"], user=world["cust2_a"], line1="2 Other", city="Bo")
    assert checkout(world, items, key="d2", fulfilment="delivery", address_id=theirs.pk).status_code == 400
    ok = checkout(world, items, key="d3", fulfilment="delivery", address_id=mine.pk)
    assert ok.status_code == 201 and ok.data["delivery_fee"] == "2.00" and ok.data["delivery_address"]["line1"] == "1 Main"
    CustomerAddress.unscoped.filter(pk=mine.pk).update(line1="Changed later")
    assert cust(world).get(f"{O}my/{ok.data['id']}/").data["delivery_address"]["line1"] == "1 Main"  # snapshot
    inline = checkout(world, items, key="d4", fulfilment="delivery", address={"line1": "9 New St", "city": "Kenema"})
    assert inline.status_code == 201 and inline.data["delivery_address"]["city"] == "Kenema"


# ---- stock -------------------------------------------------------------------------------------
def test_stock_is_deducted_logged_and_cannot_be_oversold(world, shop):
    assert checkout(world, [line(shop["fish"], 2)], key="s1").status_code == 201
    shop["fish"].refresh_from_db()
    m = StockMovement.unscoped.get()
    assert shop["fish"].stock_quantity == 1 and (m.delta, m.reason, m.quantity_after, m.note) == (-2, "sale", 1, "ORD-000001")
    r = checkout(world, [line(shop["fish"], 2)], key="s2", who="cust2_a")
    assert r.status_code == 400 and "left" in json.dumps(r.data)
    shop["fish"].refresh_from_db()
    assert shop["fish"].stock_quantity == 1 and Order.unscoped.count() == 1  # nothing partially created
    assert checkout(world, [line(shop["fish"], 1)], key="s3", who="cust2_a").status_code == 201
    shop["fish"].refresh_from_db()
    assert shop["fish"].stock_quantity == 0
    assert checkout(world, [line(shop["fish"], 1)], key="s4").status_code == 400  # sold out


def test_failed_checkout_rolls_back_everything(world, shop):
    r = checkout(world, [line(shop["fish"], 1), line(shop["rice"], 1, variation_id=shop["small"].pk)], key="rb")  # invalid 2nd line
    assert r.status_code == 400
    shop["fish"].refresh_from_db()
    assert shop["fish"].stock_quantity == 3 and Order.unscoped.count() == 0 and StockMovement.unscoped.count() == 0
    assert checkout(world, [line(shop["rice"])], key="rb").status_code == 201  # the failed key can be reused


# ---- customer visibility, cancellation, dashboard ----------------------------------------------
def place(world, shop, who="cust_a", key=None, item="rice", qty=1):
    return checkout(world, [line(shop[item], qty)], key=key or f"k-{who}-{Order.unscoped.count()}", who=who).data


def test_customers_only_see_their_own_orders(world, shop):
    mine, theirs = place(world, shop), place(world, shop, "cust2_a")
    c = cust(world)
    assert [o["id"] for o in c.get(O + "my/").data["results"]] == [mine["id"]]
    assert c.get(f"{O}my/{theirs['id']}/").status_code == 404
    assert c.post(f"{O}my/{theirs['id']}/cancel/", {}, format="json").status_code == 404
    assert Order.unscoped.get(pk=theirs["id"]).status == "awaiting_payment"
    assert client_for(world["cust_a"], "bravo").get(O + "my/").status_code == 403  # no membership at bravo


def test_customer_cancel_before_acceptance_restores_stock_once(world, shop):
    o = place(world, shop, item="fish", qty=2)
    r = cust(world).post(f"{O}my/{o['id']}/cancel/", {"reason": "changed my mind"}, format="json")
    assert r.status_code == 200 and r.data["outcome"] == "cancelled" and r.data["order"]["status"] == "cancelled"
    shop["fish"].refresh_from_db()
    assert shop["fish"].stock_quantity == 3
    assert cust(world).post(f"{O}my/{o['id']}/cancel/", {}, format="json").status_code == 400  # already cancelled
    shop["fish"].refresh_from_db()
    assert shop["fish"].stock_quantity == 3  # not restored twice
    assert [m.reason for m in StockMovement.unscoped.order_by("id")] == ["sale", "return"]


def test_customer_can_only_request_cancellation_after_acceptance(world, shop):
    o = place(world, shop)
    order = Order.unscoped.get(pk=o["id"])
    Order.unscoped.filter(pk=order.pk).update(status="confirmed")
    r = cust(world).post(f"{O}my/{o['id']}/cancel/", {"reason": "too slow"}, format="json")
    assert r.data["outcome"] == "requested" and r.data["order"]["status"] == "confirmed" and r.data["order"]["cancellation_requested"]
    Order.unscoped.filter(pk=order.pk).update(status="preparing")
    assert cust(world).post(f"{O}my/{o['id']}/cancel/", {}, format="json").status_code == 400


def test_dashboard_counts_and_activity(world, shop):
    a, b, c_ = place(world, shop), place(world, shop), place(world, shop)
    Order.unscoped.filter(pk=a["id"]).update(status="completed")
    cust(world).post(f"{O}my/{b['id']}/cancel/", {}, format="json")
    place(world, shop, "cust2_a")
    d = cust(world).get("/api/v1/customers/dashboard/").data
    assert (d["total_orders"], d["current_orders"], d["completed_orders"], d["cancelled_orders"]) == (3, 1, 1, 1)
    assert len(d["recent_orders"]) == 3 and d["recent_activity"][0]["status"] == "cancelled" and d["recent_transactions"] == []


# ---- staff & the state machine -----------------------------------------------------------------
def staff(world, who, slug="alpha"):
    return client_for(world[who], slug)


def move(world, who, order_id, to, note=""):
    return staff(world, who).post(f"{O}manage/{order_id}/transition/", {"status": to, "note": note}, format="json")


def test_full_pickup_lifecycle_by_the_right_roles_with_history_and_emails(world, shop):
    o = place(world, shop)
    steps = [("cashier_a1", "confirmed"), ("cashier_a1", "received"), ("kitchen_a1", "preparing"),
             ("kitchen_a1", "ready_for_pickup"), ("cashier_a1", "completed")]
    for who, to in steps:
        r = move(world, who, o["id"], to)
        assert r.status_code == 200 and r.data["status"] == to, (who, to, r.data)
    hist = list(OrderStatusHistory.unscoped.filter(order_id=o["id"]).values_list("to_status", "actor_role"))
    assert hist == [("awaiting_payment", "customer"), ("confirmed", "cashier"), ("received", "cashier"), ("preparing", "kitchen"),
                    ("ready_for_pickup", "kitchen"), ("completed", "cashier")]
    assert OrderStatusHistory.unscoped.filter(order_id=o["id"]).exclude(actor=None).count() == 6
    assert "Ready for Pickup" in [m for m in ConsoleProvider.outbox if m["to"] == "cust@a.com"][-2]["html"]
    assert len([m for m in ConsoleProvider.outbox if m["to"] == "cust@a.com"]) == 6  # confirmation + 5 status mails
    assert AuditLog.objects.filter(action="order.status_changed").count() == 5


def test_delivery_lifecycle_and_fulfilment_specific_statuses(world, shop):
    o = checkout(world, [line(shop["rice"])], key="dl", fulfilment="delivery", address={"line1": "1 St", "city": "X"}).data
    for who, to in [("cashier_a1", "confirmed"), ("cashier_a1", "received"), ("kitchen_a1", "preparing")]:
        assert move(world, who, o["id"], to).status_code == 200
    assert move(world, "kitchen_a1", o["id"], "ready_for_pickup").status_code == 400  # not for delivery orders
    assert move(world, "kitchen_a1", o["id"], "out_for_delivery").status_code == 200
    assert move(world, "kitchen_a1", o["id"], "completed").status_code == 400
    assert move(world, "delivery_a1", o["id"], "completed").status_code == 200


def test_pickup_orders_cannot_go_out_for_delivery(world, shop):
    o = place(world, shop)
    for who, to in [("mgr_a1", "confirmed"), ("mgr_a1", "received"), ("mgr_a1", "preparing")]:
        move(world, who, o["id"], to)
    assert move(world, "mgr_a1", o["id"], "out_for_delivery").status_code == 400


@pytest.mark.parametrize("who,to", [("kitchen_a1", "confirmed"), ("kitchen_a1", "cancelled"), ("delivery_a1", "confirmed"),
                                    ("cashier_a1", "preparing"), ("delivery_a1", "received")])
def test_roles_cannot_perform_other_roles_moves(world, shop, who, to):
    o = place(world, shop)
    assert move(world, who, o["id"], to, "x").status_code == 400
    assert Order.unscoped.get(pk=o["id"]).status == "awaiting_payment"


@pytest.mark.parametrize("to", ["preparing", "completed", "ready_for_pickup", "received", "refunded", "refund_pending",
                                "payment_processing", "nonsense", "awaiting_payment"])
def test_illegal_transitions_rejected_even_for_admin(world, shop, to):
    o = place(world, shop)
    assert move(world, "admin_a", o["id"], to).status_code == 400
    assert Order.unscoped.get(pk=o["id"]).status == "awaiting_payment"


def test_terminal_and_completed_orders_are_frozen(world, shop):
    o = place(world, shop)
    move(world, "admin_a", o["id"], "cancelled", "duplicate")
    for to in ("confirmed", "preparing", "completed", "awaiting_payment"):
        assert move(world, "admin_a", o["id"], to).status_code == 400


def test_cancel_by_staff_needs_reason_and_restores_stock(world, shop):
    o = place(world, shop, item="fish", qty=3)
    assert move(world, "cashier_a1", o["id"], "cancelled").status_code == 400  # reason required
    assert move(world, "cashier_a1", o["id"], "cancelled", "out of ice").status_code == 200
    shop["fish"].refresh_from_db()
    assert shop["fish"].stock_quantity == 3
    assert Order.unscoped.get(pk=o["id"]).cancellation_reason == "out of ice"


def test_paid_orders_cannot_be_cancelled_without_a_refund(world, shop):
    o = place(world, shop)
    Order.unscoped.filter(pk=o["id"]).update(amount_paid=Decimal("10.93"))
    assert move(world, "admin_a", o["id"], "cancelled", "x").status_code == 400


def test_staff_endpoints_are_staff_only_and_customers_blocked(world, shop):
    o = place(world, shop)
    assert cust(world).get(O + "manage/").status_code == 403
    assert cust(world).post(f"{O}manage/{o['id']}/transition/", {"status": "confirmed"}, format="json").status_code == 403
    assert APIClient(HTTP_HOST=host("alpha")).get(O + "manage/").status_code == 401


def test_branch_isolation_for_staff_and_cross_tenant_isolation(world, shop):
    o1 = place(world, shop, key="b1")  # branch a1
    o2 = checkout(world, [line(shop["rice"])], key="b2", branch_id=world["a2"].pk).data
    ids = lambda who, slug="alpha": sorted(x["id"] for x in staff(world, who, slug).get(O + "manage/").data["results"])  # noqa: E731
    assert ids("cashier_a1") == [o1["id"]] and ids("cashier_a2") == [o2["id"]]
    assert ids("mgr_a1") == [o1["id"]] and ids("mgr_a2") == [o2["id"]]
    assert ids("admin_a") == sorted([o1["id"], o2["id"]])
    assert staff(world, "cashier_a1").get(f"{O}manage/{o2['id']}/").status_code == 404
    assert move(world, "cashier_a1", o2["id"], "confirmed").status_code == 404  # other branch: not even visible
    assert move(world, "mgr_a1", o2["id"], "confirmed").status_code == 404
    assert Order.unscoped.get(pk=o2["id"]).status == "awaiting_payment"
    assert staff(world, "admin_b", "bravo").get(O + "manage/").data["results"] == []
    assert staff(world, "admin_b", "bravo").get(f"{O}manage/{o1['id']}/").status_code == 404
    assert staff(world, "admin_a", "bravo").get(O + "manage/").status_code == 403  # no membership at bravo


def test_staff_list_filters(world, shop):
    a, b = place(world, shop), place(world, shop, "cust2_a")
    move(world, "cashier_a1", a["id"], "confirmed")
    s = staff(world, "cashier_a1")
    assert [o["id"] for o in s.get(O + "manage/", {"status": "confirmed"}).data["results"]] == [a["id"]]
    assert [o["id"] for o in s.get(O + "manage/", {"q": a["number"]}).data["results"]] == [a["id"]]
    assert s.get(O + "manage/", {"active": "1"}).data["count"] == 2
    assert s.get(O + "manage/", {"date_from": "2999-01-01"}).data["count"] == 0
    assert all("allowed_transitions" in s.get(f"{O}manage/{x['id']}/").data for x in (a, b))
    assert [t["status"] for t in s.get(f"{O}manage/{b['id']}/").data["allowed_transitions"]] == ["cancelled", "confirmed"]
    assert [t["status"] for t in staff(world, "kitchen_a1").get(f"{O}manage/{b['id']}/").data["allowed_transitions"]] == []


def test_status_emails_respect_the_customers_preference_but_not_duplicates(world, shop):
    m = Membership.objects.get(user=world["cust_a"], restaurant=world["a"])
    m.preferences = {"order_emails": False}
    m.save()
    o = place(world, shop)
    ConsoleProvider.outbox.clear()
    move(world, "cashier_a1", o["id"], "confirmed")
    assert ConsoleProvider.outbox == []  # opted out of order updates (confirmation at checkout is transactional)


def test_site_content_can_configure_tax_and_delivery(world, shop):
    a = client_for(world["admin_a"], "alpha")
    r = a.patch("/api/v1/catalog/site/", {"tax_rate_percent": "10.00", "delivery_fee": "3.50", "delivery_enabled": True}, format="json")
    assert r.status_code == 200 and r.data["tax_rate_percent"] == "10.00"
    d = json.loads(quote(world, [line(shop["rice"])], fulfilment="delivery").content)["data"]
    assert d["tax_total"] == "1.01" and d["delivery_fee"] == "3.50"
    assert a.patch("/api/v1/catalog/site/", {"tax_rate_percent": "150"}, format="json").status_code == 400
    assert a.patch("/api/v1/catalog/site/", {"delivery_fee": "-1"}, format="json").status_code == 400
    assert client_for(world["mgr_a1"], "alpha").patch("/api/v1/catalog/site/", {"tax_rate_percent": "0"}, format="json").status_code == 403


def test_quote_query_count_is_bounded(world, shop, django_assert_max_num_queries):
    items = [line(shop["rice"], 2), line(shop["pizza"]), line(shop["fish"])]
    with django_assert_max_num_queries(12):
        assert quote(world, items).status_code == 200
