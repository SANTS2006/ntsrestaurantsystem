import asyncio
import json
from decimal import Decimal

import pytest
from asgiref.sync import sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.core.cache import cache
from tests.conftest import TenantClient as APIClient

from apps.accounts.services import issue_tokens
from apps.cashier.models import Shift
from apps.core.models import AuditLog
from apps.orders.models import Order, Status
from apps.payments.models import Payment, Receipt
from apps.qrmenu.models import DiningTable, QRMenuRequest
from apps.qrmenu.routing import websocket_urlpatterns
from apps.catalog.models import Product

from .conftest import client_for, host
from .test_phase5_orders import clean, line, shop  # noqa: F401  (fixtures)

Q = "/api/v1/qr-menu/"


def api(world, who, slug="alpha"):
    return client_for(world[who], slug)


def pub(slug="alpha"):
    return APIClient(HTTP_HOST=host(slug))


@pytest.fixture
def table(world, shop):
    return DiningTable.unscoped.create(restaurant=world["a"], branch=world["a1"], label="Table 4")


def submit(table, shop, slug="alpha", **over):
    body = {"items": [line(shop["rice"], 2)], "customer_name": "Dana", **over}
    return pub(slug).post(f"{Q}public/{table.qr_token}/requests/", body, format="json")


def open_shift(world, who="cashier_a1", branch="a1"):
    return Shift.unscoped.create(restaurant=world["a"], branch=world[branch], cashier=world[who], opening_cash=Decimal("0"))


# =========================== tables =============================================================
def test_manager_creates_tables_for_own_branch_with_unique_unguessable_tokens(world):
    m = api(world, "mgr_a1")
    r = m.post(Q + "tables/", {"label": "Table 1", "branch": world["a1"].pk, "seats": 4}, format="json")
    assert r.status_code == 201 and r.data["qr_url"].startswith("http://platform.test/alpha/t/")
    r2 = m.post(Q + "tables/", {"label": "Table 2", "branch": world["a1"].pk}, format="json")
    t1, t2 = DiningTable.unscoped.get(pk=r.data["id"]), DiningTable.unscoped.get(pk=r2.data["id"])
    assert t1.qr_token != t2.qr_token and len(t1.qr_token) >= 30
    assert m.post(Q + "tables/", {"label": "table 1", "branch": world["a1"].pk}, format="json").status_code == 400  # duplicate in the branch
    assert m.post(Q + "tables/", {"label": "Table 1", "branch": world["a2"].pk}, format="json").status_code == 400   # not their branch
    assert m.post(Q + "tables/", {"label": "X", "branch": world["b1"].pk}, format="json").status_code == 400          # another tenant's branch
    assert api(world, "admin_a").post(Q + "tables/", {"label": "Table 1", "branch": world["a2"].pk}, format="json").status_code == 201
    assert AuditLog.objects.filter(action="table.created").count() == 3


def test_table_permissions_and_scoping(world, table):
    for who in ("kitchen_a1", "cust_a"):
        assert api(world, who).get(Q + "tables/").status_code == 403
    assert api(world, "cashier_a1").get(Q + "tables/").status_code == 200  # cashiers can see their tables
    assert api(world, "cashier_a1").post(Q + "tables/", {"label": "Z", "branch": world["a1"].pk}, format="json").status_code == 403
    assert api(world, "cashier_a1").post(f"{Q}tables/{table.pk}/regenerate/").status_code == 403
    assert [t["id"] for t in api(world, "mgr_a1").get(Q + "tables/").data["results"]] == [table.pk]
    assert api(world, "mgr_a2").get(Q + "tables/").data["results"] == []
    assert api(world, "mgr_a2").get(f"{Q}tables/{table.pk}/").status_code == 404
    assert api(world, "admin_b", "bravo").get(f"{Q}tables/{table.pk}/").status_code == 404
    assert api(world, "mgr_a1").delete(f"{Q}tables/{table.pk}/").status_code == 405


def test_regenerate_invalidates_the_old_code_and_disable_blocks_it(world, table, shop):
    old = table.qr_token
    assert pub().get(f"{Q}public/{old}/").status_code == 200
    r = api(world, "mgr_a1").post(f"{Q}tables/{table.pk}/regenerate/")
    table.refresh_from_db()
    assert r.status_code == 200 and table.qr_token != old and table.qr_regenerated_at
    assert pub().get(f"{Q}public/{old}/").status_code == 404 and submit(DiningTable(qr_token=old), shop).status_code == 404
    assert pub().get(f"{Q}public/{table.qr_token}/").status_code == 200
    api(world, "mgr_a1").post(f"{Q}tables/{table.pk}/disable/")
    assert pub().get(f"{Q}public/{table.qr_token}/").status_code == 404
    api(world, "mgr_a1").post(f"{Q}tables/{table.pk}/enable/")
    assert pub().get(f"{Q}public/{table.qr_token}/").status_code == 200
    assert {a for a in AuditLog.objects.values_list("action", flat=True)} >= {"table.qr_regenerated", "table.disabled", "table.enabled"}


def test_qr_image_is_png_and_staff_only(world, table):
    r = api(world, "mgr_a1").get(f"{Q}tables/{table.pk}/qr/")
    assert r.status_code == 200 and r["Content-Type"] == "image/png" and r.content.startswith(b"\x89PNG") and "no-store" in r["Cache-Control"]
    assert pub().get(f"{Q}tables/{table.pk}/qr/").status_code == 401
    assert api(world, "cust_a").get(f"{Q}tables/{table.pk}/qr/").status_code == 403
    assert api(world, "mgr_a2").get(f"{Q}tables/{table.pk}/qr/").status_code == 404


# =========================== public menu & requests ===============================================
def test_scanning_opens_the_right_restaurant_branch_table_and_menu_without_leaking(world, table, shop):
    r = pub().get(f"{Q}public/{table.qr_token}/")
    d = json.loads(r.content)["data"]
    assert (d["restaurant"]["name"], d["branch"], d["table"]) == ("Alpha", "A One", "Table 4")
    assert [p["name"] for c in d["menu"] for p in c["products"]] == ["Rice", "Pizza", "Fish"] or {p["name"] for c in d["menu"] for p in c["products"]} == {"Rice", "Pizza", "Fish"}
    blob = r.content.decode()
    for secret in ("stock_quantity", "cash1@a.com", "admin@a.com", "qr_token", table.qr_token):
        assert secret not in blob
    assert "Bravo dish" not in blob
    assert pub("bravo").get(f"{Q}public/{table.qr_token}/").status_code == 404      # token from another restaurant's host
    assert pub().get(f"{Q}public/not-a-token/").status_code == 404
    assert pub().get(f"{Q}public/not-a-token/").content == pub().get(f"{Q}public/{'x' * 32}/").content  # no hint about validity
    assert APIClient(HTTP_HOST=host()).get(f"{Q}public/{table.qr_token}/").status_code == 404           # platform host


def test_request_is_not_an_order_and_creates_no_payment_or_stock_change(world, table, shop):
    r = submit(table, shop, items=[line(shop["fish"], 2)], notes="no ice")
    assert r.status_code == 201 and r.data["status"] == "new" and "not an order" in r.data["message"]
    req = QRMenuRequest.unscoped.get()
    assert (req.branch_id, req.table_id, req.status) == (world["a1"].pk, table.pk, "new") and req.client_hash and "." not in req.client_hash
    assert Order.unscoped.count() == 0 and Payment.unscoped.count() == 0
    shop["fish"].refresh_from_db()
    assert shop["fish"].stock_quantity == 3  # nothing reserved or deducted until a cashier confirms
    assert req.summary["lines"][0]["name"] == "Fish" and req.summary["total"] == "43.30"  # server-priced: 40.00 + 8.25% tax
    assert not any(k in json.dumps(req.summary) for k in ("cust@a.com", "password"))


def test_status_endpoint_exposes_only_the_status(world, table, shop):
    pid = submit(table, shop).data["public_id"]
    s = pub().get(f"{Q}public/{table.qr_token}/requests/{pid}/")
    assert s.status_code == 200 and json.loads(s.content)["data"] == {"status": "new", "reject_reason": ""}
    other = DiningTable.unscoped.create(restaurant=world["a"], branch=world["a1"], label="Table 5")
    assert pub().get(f"{Q}public/{other.qr_token}/requests/{pid}/").status_code == 404  # only via the same table's code
    assert pub().get(f"{Q}public/{table.qr_token}/requests/00000000-0000-0000-0000-000000000000/").status_code == 404


@pytest.mark.parametrize("mutate", [
    lambda s: {"items": []},
    lambda s: {"items": [{"product_id": s["bdish"].pk, "quantity": 1}]},                    # another restaurant's product
    lambda s: {"items": [{"product_id": s["rice"].pk, "quantity": 0}]},
    lambda s: {"items": [{"product_id": s["rice"].pk, "quantity": 999}]},
    lambda s: {"items": [{"product_id": s["pizza"].pk, "quantity": 1, "instructions": "x"}]},  # instructions not allowed
    lambda s: {"website": "http://spam.example"},                                               # honeypot
    lambda s: {"customer_phone": "abc"},
    lambda s: {"notes": "x" * 201},
])
def test_invalid_or_bot_requests_are_rejected(world, table, shop, mutate):
    assert submit(table, shop, **mutate(shop)).status_code == 400
    assert QRMenuRequest.unscoped.count() == 0


def test_client_prices_and_totals_are_ignored(world, table, shop):
    r = pub().post(f"{Q}public/{table.qr_token}/requests/", {"items": [{**line(shop["rice"]), "price": "0.01"}], "total": "0.01"}, format="json")
    assert r.status_code == 201 and QRMenuRequest.unscoped.get().summary["total"] == "10.93"


def test_unavailable_items_cannot_be_requested(world, table, shop):
    Product.unscoped.filter(pk=shop["rice"].pk).update(is_available=False)
    assert submit(table, shop).status_code == 400
    Product.unscoped.filter(pk=shop["rice"].pk).update(is_available=True)
    Product.unscoped.filter(pk=shop["fish"].pk).update(stock_quantity=0)
    assert submit(table, shop, items=[line(shop["fish"], 1)]).status_code == 400  # sold out


def test_guest_and_identification_policy(world, table, shop):
    st = shop["settings"]
    st.qr_identification = "phone"
    st.save()
    assert submit(table, shop, customer_name="").status_code == 400
    assert submit(table, shop, customer_phone="").status_code == 400
    assert submit(table, shop, customer_phone="+23276123456").status_code == 201
    st.qr_identification = "none"
    st.qr_guest_orders_allowed = False
    st.save()
    assert submit(table, shop).status_code == 403
    assert json.loads(pub().get(f"{Q}public/{table.qr_token}/").content)["data"]["can_request"] is False


def test_per_table_pending_cap_and_suspended_branch(world, table, shop, settings):
    settings.QR_MAX_PENDING_PER_TABLE = 2
    assert [submit(table, shop).status_code for _ in range(3)] == [201, 201, 400]
    world["a1"].status = "suspended"
    world["a1"].save()
    assert submit(table, shop).status_code == 404 and pub().get(f"{Q}public/{table.qr_token}/").status_code == 404


def test_request_throttle_limits_spam(world, table, shop, monkeypatch):
    from rest_framework.throttling import ScopedRateThrottle
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {"qr": "3/min"})
    cache.clear()
    codes = [submit(table, shop).status_code for _ in range(5)]
    assert codes[:3] == [201, 201, 201] and codes[3:] == [429, 429]
    cache.clear()


# =========================== staff handling ======================================================
def requests_for(world, who):
    return sorted(x["id"] for x in api(world, who).get(Q + "requests/").data["results"])


def test_requests_are_visible_only_to_the_tables_branch_staff(world, table, shop):
    rid = QRMenuRequest.unscoped.get(pk=submit(table, shop).data and QRMenuRequest.unscoped.latest("id").pk).pk
    assert requests_for(world, "cashier_a1") == requests_for(world, "mgr_a1") == requests_for(world, "admin_a") == [rid]
    assert requests_for(world, "cashier_a2") == requests_for(world, "mgr_a2") == []
    assert api(world, "cashier_a2").get(f"{Q}requests/{rid}/").status_code == 404
    assert api(world, "admin_b", "bravo").get(f"{Q}requests/{rid}/").status_code == 404
    for who in ("kitchen_a1", "delivery_a1", "cust_a"):
        assert api(world, who).get(Q + "requests/").status_code == 403
    d = api(world, "cashier_a1").get(f"{Q}requests/{rid}/").data
    assert (d["table"], d["branch_name"], d["summary"]["lines"][0]["quantity"], d["customer_name"]) == ("Table 4", "A One", 2, "Dana") and d["created_at"]


def convert(world, rid, who="cashier_a1", key="c1", **body):
    body = {"payment": "cash", "amount_received": "50.00", **body}
    return api(world, who).post(f"{Q}requests/{rid}/convert/", body, format="json", HTTP_IDEMPOTENCY_KEY=key)


def test_cashier_converts_a_request_into_a_paid_order_with_receipt(world, table, shop):
    submit(table, shop)
    rid = QRMenuRequest.unscoped.get().pk
    open_shift(world)
    r = convert(world, rid)
    assert r.status_code == 201, r.data
    o = Order.unscoped.get()
    assert (o.source, o.fulfilment, o.status, o.payment_status, o.customer_id, o.table_id, o.table_label) == ("qr", "dine_in", Status.CONFIRMED, "paid", None, table.pk, "Table 4")
    assert o.cashier_id == world["cashier_a1"].pk and o.branch_id == world["a1"].pk and r.data["change_given"] == "28.13"
    req = QRMenuRequest.unscoped.get()
    assert (req.status, req.order_id, req.handled_by_id) == ("converted", o.pk, world["cashier_a1"].pk)
    assert Receipt.unscoped.count() == 1 and Payment.unscoped.get().shift_id
    assert convert(world, rid, key="c1").data["order"]["id"] == o.pk and Order.unscoped.count() == 1      # same key: replay
    assert convert(world, rid, key="c2").status_code == 400 and Order.unscoped.count() == 1               # already handled
    assert json.loads(pub().get(f"{Q}public/{table.qr_token}/requests/{req.public_id}/").content)["data"]["status"] == "converted"


def test_conversion_rules(world, table, shop):
    submit(table, shop)
    rid = QRMenuRequest.unscoped.get().pk
    assert convert(world, rid, who="cashier_a1", key="n").status_code == 400            # cashier without a shift cannot take cash
    assert QRMenuRequest.unscoped.get().status == "new" and Order.unscoped.count() == 0  # nothing half-done
    assert convert(world, rid, who="cashier_a2", key="o").status_code == 404            # other branch
    for who in ("kitchen_a1", "cust_a"):
        assert convert(world, rid, who=who, key=who).status_code == 403
    assert convert(world, rid, who="mgr_a1", key="m", amount_received="1.00").status_code == 400   # not enough
    assert Order.unscoped.count() == 0
    assert api(world, "mgr_a1").post(f"{Q}requests/{rid}/convert/", {"payment": "cash", "amount_received": "50"}, format="json").status_code == 400  # no key
    later = convert(world, rid, who="mgr_a1", key="l", payment="pay_later", amount_received=None)
    assert later.status_code == 201 and Order.unscoped.get().status == Status.AWAITING_PAYMENT and Payment.unscoped.count() == 0


def test_conversion_uses_current_prices_and_checks_availability(world, table, shop):
    submit(table, shop)
    rid = QRMenuRequest.unscoped.get().pk
    Product.unscoped.filter(pk=shop["rice"].pk).update(base_price=Decimal("20.00"))
    r = convert(world, rid, who="mgr_a1", payment="pay_later", amount_received=None)
    assert r.status_code == 201 and Order.unscoped.get().subtotal == Decimal("40.00")      # priced at conversion time, never trusting the old snapshot
    submit(table, shop)
    rid2 = QRMenuRequest.unscoped.latest("id").pk
    Product.unscoped.filter(pk=shop["rice"].pk).update(is_available=False)
    assert convert(world, rid2, who="mgr_a1", key="u", payment="pay_later", amount_received=None).status_code == 400
    assert QRMenuRequest.unscoped.get(pk=rid2).status == "new"


def test_reject_request(world, table, shop):
    submit(table, shop)
    rid = QRMenuRequest.unscoped.get().pk
    assert api(world, "cashier_a2").post(f"{Q}requests/{rid}/reject/", {"reason": "x"}, format="json").status_code == 404
    r = api(world, "cashier_a1").post(f"{Q}requests/{rid}/reject/", {"reason": "kitchen closed"}, format="json")
    assert r.status_code == 200 and r.data["status"] == "rejected"
    assert json.loads(pub().get(f"{Q}public/{table.qr_token}/requests/{QRMenuRequest.unscoped.get().public_id}/").content)["data"] == {"status": "rejected", "reject_reason": "kitchen closed"}
    assert api(world, "cashier_a1").post(f"{Q}requests/{rid}/reject/", {}, format="json").status_code == 400
    assert convert(world, rid, who="mgr_a1", key="z", payment="pay_later", amount_received=None).status_code == 400
    assert AuditLog.objects.filter(action="qr.request_rejected").count() == 1 and Order.unscoped.count() == 0


def test_converted_in_person_mobile_money_request(world, table, shop):
    shop["settings"].online_payments_enabled = True
    shop["settings"].save()
    submit(table, shop)
    rid = QRMenuRequest.unscoped.get().pk
    r = convert(world, rid, who="mgr_a1", payment="mobile_money", amount_received=None, payer_phone="+23276123456")
    assert r.status_code == 201 and r.data["payment"]["status"] == "pending" and Order.unscoped.get().status == Status.PAYMENT_PROCESSING


# =========================== real time ============================================================
WS = URLRouter(websocket_urlpatterns)


def communicator(slug="alpha"):
    return WebsocketCommunicator(WS, f"/{slug}/ws/staff/", headers=[(b"host", b"platform.test")])


async def ws_login(world, who, slug="alpha"):
    c = communicator(slug)
    ok, _ = await c.connect()
    if not ok:
        return c, None
    await c.send_json_to({"type": "auth", "token": await sync_to_async(lambda: issue_tokens(world[who])["access"])()})
    out = await c.receive_output(timeout=2)
    if out["type"] == "websocket.close":
        return c, {"closed": out.get("code")}
    return c, json.loads(out["text"])


async def closed_code(c):
    out = await c.receive_output(timeout=2)
    return out.get("code") if out["type"] == "websocket.close" else None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ws_staff_connect_and_only_get_their_branch_events(world, table, shop):
    c1, ready1 = await ws_login(world, "cashier_a1")
    c2, ready2 = await ws_login(world, "cashier_a2")
    cm, readym = await ws_login(world, "mgr_a1")
    ca, readya = await ws_login(world, "admin_a")
    assert ready1 == {"type": "ready", "branches": [world["a1"].pk]} and ready2["branches"] == [world["a2"].pk]
    assert sorted(readya["branches"]) == sorted([world["a1"].pk, world["a2"].pk])
    r = await sync_to_async(submit)(table, shop, notes="hurry")
    assert r.status_code == 201
    ev = await c1.receive_json_from(timeout=2)
    assert ev["type"] == "qr.request.created" and ev["table"] == "Table 4" and ev["branch"] == "A One" and ev["lines"] == 1 and "customer_phone" not in ev
    assert (await cm.receive_json_from(timeout=2))["id"] == ev["id"] and (await ca.receive_json_from(timeout=2))["id"] == ev["id"]
    assert await c2.receive_nothing(timeout=0.4)  # the other branch's cashier hears nothing
    for c in (c1, c2, cm, ca):
        await c.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ws_rejects_everyone_who_should_not_listen(world, table, shop):
    # no auth message at all
    c = communicator()
    assert (await c.connect())[0]
    await c.send_json_to({"type": "hello"})
    assert await closed_code(c) == 4401
    # garbage token
    c = communicator()
    await c.connect()
    await c.send_json_to({"type": "auth", "token": "not-a-jwt"})
    assert await closed_code(c) == 4403
    # roles that must not receive till events, customers, and another restaurant's staff
    for who, slug in (("kitchen_a1", "alpha"), ("delivery_a1", "alpha"), ("cust_a", "alpha"), ("admin_b", "alpha"), ("admin_a", "bravo")):
        c, res = await ws_login(world, who, slug)
        assert res == {"closed": 4403}, (who, res)
    # platform host and unknown host are refused outright
    assert (await communicator("platform-nope").connect())[0] is False
    c = WebsocketCommunicator(WS, "/ws/staff/", headers=[(b"host", b"platform.test")])
    assert (await c.connect())[0] is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ws_revoked_token_and_silent_connection(world, table, shop, settings):
    from apps.accounts.services import revoke_tokens
    token = await sync_to_async(lambda: issue_tokens(world["cashier_a1"])["access"])()
    await sync_to_async(revoke_tokens)(world["cashier_a1"])  # e.g. password changed or deactivated afterwards
    c = communicator()
    await c.connect()
    await c.send_json_to({"type": "auth", "token": token})
    assert await closed_code(c) == 4403
    settings.WS_AUTH_TIMEOUT_SECONDS = 0.2
    c = communicator()
    await c.connect()
    assert await closed_code(c) == 4401  # connected but never authenticated


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ws_ping_and_update_events_on_conversion(world, table, shop):
    c, ready = await ws_login(world, "mgr_a1")
    await c.send_json_to({"type": "ping"})
    assert (await c.receive_json_from(timeout=2)) == {"type": "pong"}
    await sync_to_async(submit)(table, shop)
    assert (await c.receive_json_from(timeout=2))["type"] == "qr.request.created"
    rid = await sync_to_async(lambda: QRMenuRequest.unscoped.get().pk)()
    r = await sync_to_async(lambda: convert(world, rid, who="mgr_a1", payment="pay_later", amount_received=None))()
    assert r.status_code == 201
    assert await c.receive_json_from(timeout=2) == {"type": "qr.request.updated", "id": rid, "status": "converted"}
    await c.disconnect()


def test_events_are_not_published_for_rolled_back_requests(world, table, shop, monkeypatch):
    sent = []
    monkeypatch.setattr("apps.qrmenu.realtime._send", lambda *a, **k: sent.append(a))
    from django.db import transaction as tx
    with pytest.raises(RuntimeError), tx.atomic():
        from apps.qrmenu.realtime import notify_branch
        notify_branch(world["a"].pk, world["a1"].pk, {"type": "x"})
        raise RuntimeError("boom")
    assert sent == []


def test_a_down_channel_layer_does_not_break_the_diner_request(world, table, shop, monkeypatch):
    monkeypatch.setattr("apps.qrmenu.realtime.get_channel_layer", lambda: (_ for _ in ()).throw(RuntimeError("redis down")))
    assert submit(table, shop).status_code == 201  # live push is best-effort; polling still works


def test_websocket_application_enforces_allowed_origins():
    import config.asgi as asgi
    assert asgi.application.application_mapping["websocket"].__class__.__name__ == "OriginValidator"
