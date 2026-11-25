import csv
import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Role, SetupToken, User
from apps.cashier.models import Shift
from apps.core.models import AuditLog
from apps.notifications.providers import ConsoleProvider
from apps.orders.models import Order, OrderItem, OrderStatusHistory
from apps.payments.models import Payment, Refund
from apps.tenants.models import Branch

from .conftest import PW, client_for, host

B = "/api/v1/restaurants/branches/"
S = "/api/v1/staff/members/"
R = "/api/v1/reports/"


@pytest.fixture(autouse=True)
def clean(db):
    ConsoleProvider.outbox.clear()
    cache.clear()


def api(world, who, slug="alpha"):
    return client_for(world[who], slug)


# =========================== branches =========================================================
def test_admin_manages_branches_and_codes_are_unique_per_restaurant(world):
    a = api(world, "admin_a")
    r = a.post(B, {"name": "Harbour", "code": "hb", "address": "Pier 1", "operating_hours": {"monday": "08:00-22:00"}}, format="json")
    assert r.status_code == 201 and r.data["code"] == "HB" and r.data["status"] == "active"
    assert a.post(B, {"name": "Dup", "code": "HB"}, format="json").status_code == 400
    assert a.patch(f"{B}{r.data['id']}/", {"code": "A1"}, format="json").status_code == 400  # taken by another Alpha branch
    assert api(world, "admin_b", "bravo").post(B, {"name": "Harbour B", "code": "HB"}, format="json").status_code == 201  # other tenant: fine
    assert a.patch(f"{B}{r.data['id']}/", {"operating_hours": ["x"]}, format="json").status_code == 400
    assert a.patch(f"{B}{r.data['id']}/", {"name": "Harbour Road", "phone": "123456"}, format="json").status_code == 200
    assert a.delete(f"{B}{r.data['id']}/").status_code == 405
    assert AuditLog.objects.filter(action="branch.created").count() == 2 and AuditLog.objects.filter(action="branch.updated").exists()


def test_managers_and_staff_cannot_change_branches(world):
    for who in ("mgr_a1", "cashier_a1", "cust_a"):
        c = api(world, who)
        assert c.post(B, {"name": "X", "code": "X"}, format="json").status_code == 403
        assert c.post(f"{B}{world['a1'].pk}/suspend/").status_code == 403
        assert c.post(f"{B}{world['a1'].pk}/assign-manager/", {"user_id": None}, format="json").status_code == 403
    assert api(world, "mgr_a1").patch(f"{B}{world['a1'].pk}/", {"name": "Mine"}, format="json").status_code == 403


def test_status_and_manager_cannot_be_set_by_plain_patch_and_cross_tenant_is_blocked(world):
    a = api(world, "admin_a")
    a.patch(f"{B}{world['a1'].pk}/", {"status": "suspended", "manager": world["mgr_a1"].pk}, format="json")
    world["a1"].refresh_from_db()
    assert world["a1"].status == "active" and world["a1"].manager_id is None
    assert a.post(f"{B}{world['b1'].pk}/suspend/").status_code == 404
    assert a.post(f"{B}{world['b1'].pk}/assign-manager/", {"user_id": None}, format="json").status_code == 404


def test_suspend_and_activate_branch_with_effects(world):
    a = api(world, "admin_a")
    s = Shift.unscoped.create(restaurant=world["a"], branch=world["a1"], cashier=world["cashier_a1"], opening_cash=Decimal("0"))
    assert a.post(f"{B}{world['a1'].pk}/suspend/").status_code == 400  # open shift blocks it
    Shift.unscoped.filter(pk=s.pk).update(status="closed")
    r = a.post(f"{B}{world['a1'].pk}/suspend/", {"reason": "renovation"}, format="json")
    assert r.status_code == 200 and r.data["status"] == "suspended"
    assert AuditLog.objects.get(action="branch.suspended").metadata["reason"] == "renovation"
    # a suspended branch takes no new shifts
    assert api(world, "cashier_a1").post("/api/v1/cashier/shift/open/", {"opening_cash": "10"}, format="json").status_code == 400
    assert a.post(f"{B}{world['a1'].pk}/activate/").data["status"] == "active"
    assert api(world, "cashier_a1").post("/api/v1/cashier/shift/open/", {"opening_cash": "10"}, format="json").status_code == 201


def test_assign_manager_moves_access_between_managers(world):
    a = api(world, "admin_a")
    r = a.post(f"{B}{world['a2'].pk}/assign-manager/", {"user_id": world["mgr_a1"].pk}, format="json")
    assert r.status_code == 200 and r.data["manager"] == world["mgr_a1"].pk and r.data["manager_name"] == "mgr1"
    assert {b["code"] for b in api(world, "mgr_a1").get(B).data["results"]} == {"A1", "A2"}  # gained access
    a.post(f"{B}{world['a2'].pk}/assign-manager/", {"user_id": world["mgr_a2"].pk}, format="json")
    assert {b["code"] for b in api(world, "mgr_a1").get(B).data["results"]} == {"A1"}  # previous manager lost it
    assert a.post(f"{B}{world['a2'].pk}/assign-manager/", {"user_id": world["cashier_a1"].pk}, format="json").status_code == 400  # not a manager
    assert a.post(f"{B}{world['a2'].pk}/assign-manager/", {"user_id": world["admin_b"].pk}, format="json").status_code == 400  # other tenant
    assert a.post(f"{B}{world['a2'].pk}/assign-manager/", {"user_id": None}, format="json").data["manager"] is None
    assert {b["code"] for b in api(world, "mgr_a2").get(B).data["results"]} == set()


# =========================== staff ============================================================
def ids(resp):
    return sorted(x["id"] for x in resp.data["results"])


def mid(world, who):
    return Membership.objects.get(user=world[who], restaurant=world["a"]).pk


def test_staff_list_is_scoped_and_never_includes_customers(world):
    admin_view = api(world, "admin_a").get(S).data["results"]
    assert {x["email"] for x in admin_view} == {"admin@a.com", "mgr1@a.com", "cash1@a.com", "kitchen1@a.com", "deliv1@a.com", "cash2@a.com", "mgr2@a.com"}
    m1 = {x["email"] for x in api(world, "mgr_a1").get(S).data["results"]}
    assert m1 == {"mgr1@a.com", "cash1@a.com", "kitchen1@a.com", "deliv1@a.com"}  # branch A1 only; admin and A2 staff hidden
    assert {x["email"] for x in api(world, "mgr_a2").get(S).data["results"]} == {"mgr2@a.com", "cash2@a.com"}
    assert api(world, "admin_b", "bravo").get(S).data["results"][0]["email"] == "admin@b.com" and api(world, "admin_b", "bravo").get(S).data["count"] == 1
    for who in ("cashier_a1", "kitchen_a1", "cust_a"):
        assert api(world, who).get(S).status_code == 403
    assert APIClient(HTTP_HOST=host("alpha")).get(S).status_code == 401
    assert [x["email"] for x in api(world, "admin_a").get(S, {"role": "cashier", "q": "cash2"}).data["results"]] == ["cash2@a.com"]
    assert api(world, "mgr_a2").get(f"{S}{mid(world, 'cashier_a1')}/").status_code == 404  # other branch's staff: not even visible
    assert api(world, "admin_b", "bravo").get(f"{S}{mid(world, 'cashier_a1')}/").status_code == 404


def patch(world, who, target, body, slug="alpha"):
    return api(world, who, slug).patch(f"{S}{mid(world, target)}/", body, format="json")


def test_manager_can_edit_lower_staff_within_own_branches(world):
    r = patch(world, "mgr_a1", "cashier_a1", {"full_name": "Cash One", "phone": "+23276000999"})
    assert r.status_code == 200 and r.data["full_name"] == "Cash One" and r.data["phone"] == "+23276000999"
    r = patch(world, "mgr_a1", "cashier_a1", {"role": "kitchen"})
    assert r.status_code == 200 and r.data["role"] == "kitchen"
    assert patch(world, "mgr_a1", "kitchen_a1", {"branch_ids": [world["a1"].pk]}).status_code == 200
    assert AuditLog.objects.filter(action="staff.updated").count() == 2  # the no-op branch edit changes nothing, so logs nothing


@pytest.mark.parametrize("target,body", [
    ("mgr_a1", {"full_name": "self edit"}),                       # yourself
    ("admin_a", {"full_name": "boss"}),                            # a superior
    ("cashier_a2", {"full_name": "other branch"}),                 # staff of a branch you do not manage
    ("cashier_a1", {"role": "manager"}),                           # escalation to your own level
    ("cashier_a1", {"role": "restaurant_admin"}),                  # escalation above you
    ("cashier_a1", {"branch_ids": [1_000_000]}),                   # unknown branch
])
def test_manager_cannot_escalate_or_reach_beyond_scope(world, target, body):
    before = Membership.objects.filter(restaurant=world["a"]).values_list("pk", "role")
    before = sorted(before)
    r = patch(world, "mgr_a1", target, body)
    assert r.status_code in (400, 404), (target, body, r.data)
    assert sorted(Membership.objects.filter(restaurant=world["a"]).values_list("pk", "role")) == before


def test_manager_cannot_grant_branches_they_do_not_manage(world):
    assert patch(world, "mgr_a1", "cashier_a1", {"branch_ids": [world["a1"].pk, world["a2"].pk]}).status_code == 400
    assert patch(world, "mgr_a1", "cashier_a1", {"branch_ids": [world["b1"].pk]}).status_code == 400
    assert list(Membership.objects.get(pk=mid(world, "cashier_a1")).branches.values_list("pk", flat=True)) == [world["a1"].pk]


def test_manager_cannot_edit_someone_who_also_works_at_another_branch(world):
    Membership.objects.get(pk=mid(world, "kitchen_a1")).branches.add(world["a2"])
    r = patch(world, "mgr_a1", "kitchen_a1", {"full_name": "x"})
    assert r.status_code == 400 and "branches you do not manage" in str(r.data)
    assert patch(world, "admin_a", "kitchen_a1", {"full_name": "Kitchen Two"}).status_code == 200


def test_admin_rules_on_roles_and_branches(world):
    assert patch(world, "admin_a", "cashier_a1", {"role": "manager", "branch_ids": [world["a1"].pk, world["a2"].pk]}).status_code == 200
    assert patch(world, "admin_a", "cashier_a1", {"role": "restaurant_admin"}).status_code == 400  # admins do not create admins
    assert patch(world, "admin_a", "admin_a", {"full_name": "self"}).status_code == 400
    assert patch(world, "admin_a", "cashier_a1", {"role": "customer"}).status_code == 400
    assert patch(world, "admin_a", "cashier_a2", {"branch_ids": []}).status_code == 400  # branch roles need a branch
    assert patch(world, "admin_b", "cashier_a1", {"full_name": "x"}, slug="bravo").status_code == 404
    pa = api(world, "platform", None)
    assert pa.patch(f"{S}{mid(world, 'cashier_a1')}/", {"full_name": "x"}, format="json").status_code == 403  # platform host does not serve tenant staff


def test_demoted_manager_stops_being_branch_manager(world):
    api(world, "admin_a").post(f"{B}{world['a1'].pk}/assign-manager/", {"user_id": world["mgr_a1"].pk}, format="json")
    patch(world, "admin_a", "mgr_a1", {"role": "cashier"})
    world["a1"].refresh_from_db()
    assert world["a1"].manager_id is None


def test_shared_identity_name_cannot_be_changed_from_another_restaurant(world):
    Membership.objects.create(user=world["cashier_a1"], restaurant=world["b"], role="cashier")
    r = patch(world, "admin_a", "cashier_a1", {"full_name": "Hijack"})
    assert r.status_code == 400 and "elsewhere" in str(r.data)
    assert patch(world, "admin_a", "cashier_a1", {"branch_ids": [world["a1"].pk, world["a2"].pk]}).status_code == 200  # role/branch edits are fine


def test_deactivation_ends_access_immediately_and_is_reversible(world):
    token = APIClient(HTTP_HOST=host("alpha")).post("/api/v1/auth/login/", {"email": "cash1@a.com", "password": PW}, format="json").data["data"]["access"]
    c = APIClient(HTTP_HOST=host("alpha"))
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert c.get("/api/v1/auth/me/").status_code == 200
    r = api(world, "mgr_a1").post(f"{S}{mid(world, 'cashier_a1')}/deactivate/", {"reason": "left"}, format="json")
    assert r.status_code == 200 and r.data["is_active"] is False
    assert c.get("/api/v1/auth/me/").status_code == 401  # token revoked
    assert APIClient(HTTP_HOST=host("alpha")).post("/api/v1/auth/login/", {"email": "cash1@a.com", "password": PW}, format="json").status_code == 401
    assert api(world, "admin_a").get(S, {"active": "0"}).data["count"] == 1
    assert api(world, "mgr_a1").post(f"{S}{mid(world, 'cashier_a1')}/activate/").data["is_active"] is True
    assert APIClient(HTTP_HOST=host("alpha")).post("/api/v1/auth/login/", {"email": "cash1@a.com", "password": PW}, format="json").status_code == 200
    assert AuditLog.objects.filter(action__in=["staff.deactivated", "staff.activated"]).count() == 2


def test_cannot_deactivate_self_peers_superiors_or_someone_with_an_open_shift(world):
    for who, target in (("mgr_a1", "mgr_a1"), ("mgr_a1", "admin_a"), ("admin_a", "admin_a"), ("mgr_a1", "cashier_a2")):
        assert api(world, who).post(f"{S}{mid(world, target)}/deactivate/").status_code in (400, 404), (who, target)
    Shift.unscoped.create(restaurant=world["a"], branch=world["a1"], cashier=world["cashier_a1"], opening_cash=Decimal("0"))
    r = api(world, "mgr_a1").post(f"{S}{mid(world, 'cashier_a1')}/deactivate/")
    assert r.status_code == 400 and "open cashier shift" in str(r.data)
    assert Membership.objects.get(pk=mid(world, "cashier_a1")).is_active


def test_resend_invite_for_pending_staff_only(world):
    inv = api(world, "mgr_a1").post("/api/v1/staff/invitations/", {"full_name": "New Hire", "email": "hire@a.com", "role": "kitchen", "branch_ids": [world["a1"].pk]}, format="json")
    assert inv.status_code == 201
    new = Membership.objects.get(user__email="hire@a.com")
    assert api(world, "mgr_a1").get(f"{S}{new.pk}/").data["invite_pending"] is True
    old_token = SetupToken.objects.get(user=new.user).token_hash
    ConsoleProvider.outbox.clear()
    assert api(world, "mgr_a1").post(f"{S}{new.pk}/resend-invite/").status_code == 200
    assert "setup-password" in ConsoleProvider.outbox[-1]["html"] and ConsoleProvider.outbox[-1]["to"] == "hire@a.com"
    assert SetupToken.objects.get(user=new.user, used_at__isnull=True).token_hash != old_token  # earlier link no longer works
    assert api(world, "mgr_a1").post(f"{S}{mid(world, 'cashier_a1')}/resend-invite/").status_code == 400  # already active
    assert api(world, "mgr_a2").post(f"{S}{new.pk}/resend-invite/").status_code == 404


def test_staff_activity_review_is_scoped_and_minimal(world):
    from apps.core.models import audit
    audit("test.action", actor=world["cashier_a1"], restaurant=world["a"], metadata={"secret": "x"})
    rows = api(world, "mgr_a1").get(f"{S}{mid(world, 'cashier_a1')}/activity/").data
    assert rows and rows[0]["action"] == "test.action" and "metadata" not in rows[0]
    assert api(world, "mgr_a2").get(f"{S}{mid(world, 'cashier_a1')}/activity/").status_code == 404
    assert api(world, "mgr_a1").get(f"{S}{mid(world, 'admin_a')}/activity/").status_code == 404


# =========================== reports ==========================================================
_n = {"i": 0}


def mk_order(world, branch, total, status="completed", source="online", paid=None, method="cash", cashier=None, customer=None,
             item="Rice", qty=1, days_ago=0, name="Walk-in"):
    _n["i"] += 1
    when = timezone.now() - timedelta(days=days_ago)
    paid = Decimal(paid) if paid is not None else Decimal("0")
    o = Order.unscoped.create(restaurant=world["a"], branch=branch, number=f"T-{_n['i']:05d}", customer=customer, cashier=cashier, source=source,
                              status=status, fulfilment="pickup", payment_method=method if method != "mobile_money" else "mobile_money",
                              payment_status="paid" if paid >= Decimal(total) else "unpaid", contact_name=name, contact_phone="000", currency="USD",
                              subtotal=Decimal(total), total=Decimal(total), amount_paid=paid)
    Order.unscoped.filter(pk=o.pk).update(created_at=when)
    OrderItem.unscoped.create(restaurant=world["a"], order=o, product_name=item, unit_price=Decimal(total) / qty, quantity=qty, line_total=Decimal(total))
    if paid > 0:
        p = Payment.unscoped.create(restaurant=world["a"], branch=branch, order=o, reference=f"P-{_n['i']}", provider="cash" if method == "cash" else "simulated",
                                    method=method, status="succeeded", amount=paid, currency="USD", paid_at=when, recorded_by=cashier if method == "cash" else None)
        return o, p
    return o, None


@pytest.fixture
def data(world):
    c1, c2 = world["cashier_a1"], world["cashier_a2"]
    a1, a2 = world["a1"], world["a2"]
    out = {}
    out["o1"], out["p1"] = mk_order(world, a1, "30.00", paid="30.00", cashier=c1, item="Rice", qty=3, customer=world["cust_a"])
    out["o2"], out["p2"] = mk_order(world, a1, "20.00", paid="20.00", method="mobile_money", source="online", item="Fish", qty=1, customer=world["cust_a"])
    out["o3"], _ = mk_order(world, a1, "15.00", status="confirmed", item="Rice", qty=1, customer=world["cust2_a"])          # accepted, unpaid -> outstanding
    out["o4"], _ = mk_order(world, a1, "99.00", status="cancelled", item="Ghost")                                          # excluded from booked sales
    out["o5"], out["p5"] = mk_order(world, a2, "50.00", paid="50.00", source="cashier", cashier=c2, item="Rice", qty=2)  # other branch
    out["o6"], out["p6"] = mk_order(world, a1, "10.00", paid="10.00", days_ago=40, item="Old")                          # outside default range
    Refund.unscoped.create(restaurant=world["a"], branch=a1, payment=out["p1"], order=out["o1"], reference="R1", amount=Decimal("5.00"), reason="cold", status="succeeded")
    OrderStatusHistory.unscoped.create(restaurant=world["a"], order=out["o1"], to_status="confirmed", actor=c1, actor_role="cashier")
    OrderStatusHistory.unscoped.create(restaurant=world["a"], order=out["o1"], to_status="preparing", actor=world["kitchen_a1"], actor_role="kitchen")
    return out


def rep(world, who, slug="alpha", **params):
    return api(world, who, slug).get(R + "branch/", params)


def test_manager_report_figures_are_exact_and_branch_scoped(world, data):
    d = rep(world, "mgr_a1").data
    assert d["orders"] == {"total": 4, "completed": 2, "pending": 1, "cancelled": 1}
    assert d["sales"]["booked"] == "65.00"          # 30 + 20 + 15; cancelled 99 excluded
    assert d["sales"]["collected"] == "50.00" and d["sales"]["refunds"] == "5.00" and d["sales"]["net_collected"] == "45.00"
    assert d["sales"]["outstanding"] == "15.00"     # accepted but unpaid
    assert d["payment_breakdown"] == {"cash": "30.00", "mobile_money": "20.00", "online": "50.00", "in_person": "0.00"}
    assert [(p["name"], p["quantity"], p["revenue"]) for p in d["top_products"]][:2] == [("Rice", 4, "45.00"), ("Fish", 1, "20.00")]
    assert "Ghost" not in str(d["top_products"]) and "Old" not in str(d["top_products"])
    assert d["customers"] == {"ordering": 2, "repeat": 1}
    assert [b["name"] for b in d["by_branch"]] == ["A One"]  # no sight of A Two
    assert d["sales"]["collected"] != "100.00"


def test_admin_sees_consolidated_report_and_branch_comparison(world, data):
    d = rep(world, "admin_a").data
    assert d["sales"]["collected"] == "100.00" and d["sales"]["booked"] == "115.00" and d["sales"]["net_collected"] == "95.00"
    by = {b["name"]: b for b in d["by_branch"]}
    assert (by["A One"]["collected"], by["A Two"]["collected"], by["A Two"]["orders"]) == ("50.00", "50.00", 1)
    assert by["A One"]["net_collected"] == "45.00"
    one = rep(world, "admin_a", branch=world["a2"].pk).data
    assert one["sales"]["collected"] == "50.00" and [b["name"] for b in one["by_branch"]] == ["A Two"]


def test_series_rollups_and_date_filters(world, data):
    d = rep(world, "mgr_a1").data
    days = d["series"]
    assert len(days) == 30 and days[-1]["collected"] == "50.00" and days[-1]["refunds"] == "5.00" and days[-1]["net"] == "45.00"
    assert all(x["collected"] == "0.00" for x in days[:-1])  # empty days are present, not missing
    wk = rep(world, "mgr_a1", group="week").data["series"]
    mo = rep(world, "mgr_a1", group="month").data["series"]
    assert sum(Decimal(x["collected"]) for x in wk) == sum(Decimal(x["collected"]) for x in mo) == Decimal("50.00")
    wide = rep(world, "mgr_a1", **{"from": (timezone.now() - timedelta(days=60)).date().isoformat()}).data
    assert wide["sales"]["collected"] == "60.00" and wide["orders"]["total"] == 5  # the 40-day-old order is now inside
    today = timezone.now().date().isoformat()
    assert rep(world, "mgr_a1", **{"from": today, "to": today}).data["sales"]["collected"] == "50.00"
    old = (timezone.now() - timedelta(days=40)).date().isoformat()
    assert rep(world, "mgr_a1", **{"from": old, "to": old}).data["sales"]["collected"] == "10.00"


def test_cashier_performance_and_staff_activity(world, data):
    Shift.unscoped.create(restaurant=world["a"], branch=world["a1"], cashier=world["cashier_a1"], opening_cash=Decimal("0"), status="closed",
                          closed_at=timezone.now(), expected_cash=Decimal("30"), actual_cash=Decimal("28"), variance=Decimal("-2"))
    d = rep(world, "mgr_a1").data
    assert [c["name"] for c in d["cashiers"]] == ["cash1"]  # the A2 cashier is invisible to the A1 manager
    c = d["cashiers"][0]
    assert (c["cash"], c["orders_entered"], c["shifts_closed"], c["variance"]) == ("30.00", 1, 1, "-2.00")
    assert {(s["role"], s["actions"]) for s in d["staff_activity"]} == {("cashier", 1), ("kitchen", 1)}
    adm = rep(world, "admin_a").data
    assert {c["name"] for c in adm["cashiers"]} == {"cash1", "cash2"}


def test_inventory_summary_in_report(world, data):
    from apps.catalog.models import Category, Product
    cat = Category.unscoped.create(restaurant=world["a"], name="C", slug="c")
    Product.unscoped.create(restaurant=world["a"], category=cat, name="Low item", slug="low", base_price=Decimal("1"), track_inventory=True, stock_quantity=2, low_stock_threshold=5)
    Product.unscoped.create(restaurant=world["a"], category=cat, name="Fine", slug="fine", base_price=Decimal("1"), track_inventory=True, stock_quantity=50)
    inv = rep(world, "mgr_a1").data["inventory"]
    assert inv["low_stock_count"] == 1 and inv["low_stock"][0]["name"] == "Low item"


@pytest.mark.parametrize("who", ["cashier_a1", "kitchen_a1", "cust_a"])
def test_reports_forbidden_for_non_managers(world, who):
    assert rep(world, who).status_code == 403
    assert api(world, who).get(R + "export/").status_code == 403


def test_report_access_and_validation(world, data):
    assert APIClient(HTTP_HOST=host("alpha")).get(R + "branch/").status_code == 401
    assert rep(world, "mgr_a1", branch=world["a2"].pk).status_code == 404       # branch outside scope
    assert rep(world, "mgr_a1", branch=world["b1"].pk).status_code == 404       # another tenant's branch
    assert rep(world, "mgr_a1", branch="abc").status_code == 404
    assert rep(world, "admin_a", branch=world["b1"].pk).status_code == 404
    assert rep(world, "mgr_a1", **{"from": "nope"}).status_code == 400
    assert rep(world, "mgr_a1", **{"from": "2026-02-01", "to": "2026-01-01"}).status_code == 400
    assert rep(world, "mgr_a1", **{"from": "2020-01-01", "to": "2026-01-01"}).status_code == 400   # range cap
    assert rep(world, "mgr_a1", group="year").status_code == 400
    bravo = rep(world, "admin_b", "bravo").data
    assert bravo["sales"]["collected"] == "0.00" and bravo["orders"]["total"] == 0  # no leakage between restaurants
    assert api(world, "platform", None).get(R + "branch/").status_code == 403       # tenant reports are not served on the platform host


def test_report_uses_a_bounded_number_of_queries(world, data, django_assert_max_num_queries):
    with django_assert_max_num_queries(40):
        assert rep(world, "admin_a").status_code == 200


def read_csv(resp):
    return list(csv.reader(io.StringIO(resp.content.decode())))


def test_exports_are_scoped_privacy_safe_and_audited(world, data):
    r = api(world, "mgr_a1").get(R + "export/", {"type": "orders"})
    assert r.status_code == 200 and r["Content-Type"].startswith("text/csv") and "attachment" in r["Content-Disposition"]
    rows = read_csv(r)
    assert rows[0][0] == "order_number" and len(rows) == 5 and {x[2] for x in rows[1:]} == {"A One"}  # 4 orders in range, branch A1 only
    assert "Walk-in" not in r.content.decode() and "000" not in [c for row in rows for c in row[:1]]  # no customer names/phones
    pay = read_csv(api(world, "mgr_a1").get(R + "export/", {"type": "payments"}))
    assert pay[0][0] == "reference" and len(pay) == 3 and sum(Decimal(x[6]) for x in pay[1:]) == Decimal("50.00")
    assert len(read_csv(api(world, "admin_a").get(R + "export/", {"type": "payments"}))) == 4
    assert api(world, "mgr_a1").get(R + "export/", {"type": "customers"}).status_code == 400
    assert api(world, "mgr_a1").get(R + "export/", {"branch": world["a2"].pk}).status_code == 404
    assert AuditLog.objects.filter(action="report.exported").count() == 3


def test_csv_formula_injection_is_neutralised(world, data):
    User.objects.filter(pk=world["cashier_a1"].pk).update(full_name='=HYPERLINK("http://evil","x")')
    pay = read_csv(api(world, "mgr_a1").get(R + "export/", {"type": "payments"}))
    names = [row[8] for row in pay[1:]]
    assert any(n.startswith("'=HYPERLINK") for n in names) and not any(n.startswith("=") for n in names)


def test_refunded_money_is_not_counted_as_outstanding(world):
    o, p = mk_order(world, world["a1"], "39.00", status="confirmed", paid="39.00", item="Rice")
    Refund.unscoped.create(restaurant=world["a"], branch=world["a1"], payment=p, order=o, reference="R9", amount=Decimal("9.00"), reason="cold", status="succeeded")
    Order.unscoped.filter(pk=o.pk).update(amount_paid=Decimal("30.00"))  # what the refund flow does
    d = rep(world, "mgr_a1").data
    assert d["sales"]["outstanding"] == "0.00" and d["sales"]["refunds"] == "9.00"
    mk_order(world, world["a1"], "12.00", status="received", item="Rice")  # genuinely unpaid, accepted
    assert rep(world, "mgr_a1").data["sales"]["outstanding"] == "12.00"
