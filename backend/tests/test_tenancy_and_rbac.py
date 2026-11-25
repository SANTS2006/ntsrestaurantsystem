import pytest
from django.core.exceptions import ValidationError
from tests.conftest import TenantClient as APIClient

from apps.accounts.models import Role
from apps.accounts.permissions import can_assign_role
from apps.core.models import AuditLog, audit
from apps.core.tenancy import tenant_context
from apps.tenants.models import Branch, Restaurant, RestaurantDomain

from .conftest import PW, client_for, host


# ---- tenant resolution -------------------------------------------------------------------------
def test_tenant_resolved_from_subdomain_and_public_branding(world):
    r = APIClient(HTTP_HOST=host("alpha")).get("/api/v1/restaurants/current/")
    assert r.status_code == 200 and r.data["data"]["slug"] == "alpha"


def test_unknown_host_404_and_header_cannot_override_tenant(world):
    assert APIClient(HTTP_HOST="evil.example.org").get("/api/v1/restaurants/current/").status_code == 404
    c = APIClient(HTTP_HOST=host("alpha"), HTTP_X_TENANT="bravo")
    assert c.get("/api/v1/restaurants/current/").data["data"]["slug"] == "alpha"


def test_suspended_restaurant_blocked(world):
    Restaurant.objects.filter(slug="alpha").update(status="suspended")
    assert APIClient(HTTP_HOST=host("alpha")).get("/api/v1/restaurants/current/").status_code == 403


def test_custom_domain_requires_verification(world):
    RestaurantDomain.objects.create(restaurant=world["a"], hostname="Alpha-Food.com", is_verified=False)
    assert APIClient(HTTP_HOST="alpha-food.com").get("/api/v1/restaurants/current/").status_code == 404
    RestaurantDomain.objects.filter(hostname="alpha-food.com").update(is_verified=True)
    assert APIClient(HTTP_HOST="alpha-food.com").get("/api/v1/restaurants/current/").status_code == 200


def test_health_endpoints_work_on_any_host(db):
    c = APIClient(HTTP_HOST="10.0.0.5")
    assert c.get("/healthz").status_code == 200
    assert c.get("/readyz").status_code == 200


# ---- cross-tenant isolation --------------------------------------------------------------------
def test_restaurant_admin_cannot_use_another_tenant(world):
    # Admin of A holding a valid token, calling B's host: no membership there -> denied.
    c = client_for(world["admin_a"], "bravo")
    assert c.get("/api/v1/restaurants/branches/").status_code == 403


def test_idor_other_tenants_branch_not_reachable(world):
    c = client_for(world["admin_a"], "alpha")
    assert c.get(f"/api/v1/restaurants/branches/{world['b1'].pk}/").status_code == 404
    assert c.patch(f"/api/v1/restaurants/branches/{world['b1'].pk}/", {"name": "pwn"}, format="json").status_code == 404
    world["b1"].refresh_from_db()
    assert world["b1"].name == "B One"


def test_restaurant_field_cannot_be_mass_assigned(world):
    c = client_for(world["admin_a"], "alpha")
    r = c.post("/api/v1/restaurants/branches/", {"name": "New", "code": "N1", "restaurant": world["b"].pk}, format="json")
    assert r.status_code == 201
    assert Branch.unscoped.get(code="N1").restaurant_id == world["a"].pk


def test_platform_admin_has_global_access(world):
    assert client_for(world["platform"], "alpha").get("/api/v1/restaurants/branches/").status_code == 200
    assert client_for(world["platform"], "bravo").get("/api/v1/restaurants/branches/").status_code == 200


# ---- branch isolation & roles ------------------------------------------------------------------
def test_manager_sees_only_assigned_branch(world):
    r = client_for(world["mgr_a1"], "alpha").get("/api/v1/restaurants/branches/")
    assert r.status_code == 200
    assert [b["code"] for b in r.data["results"]] == ["A1"]
    assert client_for(world["mgr_a1"], "alpha").get(f"/api/v1/restaurants/branches/{world['a2'].pk}/").status_code == 404


def test_admin_sees_all_branches_of_own_restaurant_only(world):
    r = client_for(world["admin_a"], "alpha").get("/api/v1/restaurants/branches/")
    assert sorted(b["code"] for b in r.data["results"]) == ["A1", "A2"]


def test_manager_cannot_create_or_edit_branches(world):
    c = client_for(world["mgr_a1"], "alpha")
    assert c.post("/api/v1/restaurants/branches/", {"name": "x", "code": "X"}, format="json").status_code == 403
    assert c.patch(f"/api/v1/restaurants/branches/{world['a1'].pk}/", {"name": "x"}, format="json").status_code == 403


def test_cashier_and_customer_blocked_from_branch_admin(world):
    assert client_for(world["cashier_a1"], "alpha").get("/api/v1/restaurants/branches/").status_code == 403
    assert client_for(world["cust_a"], "alpha").get("/api/v1/restaurants/branches/").status_code == 403


def test_anonymous_blocked(world):
    assert APIClient(HTTP_HOST=host("alpha")).get("/api/v1/restaurants/branches/").status_code == 401


def test_role_assignment_cannot_escalate():
    assert can_assign_role(Role.PLATFORM_ADMIN, Role.RESTAURANT_ADMIN)
    assert can_assign_role(Role.RESTAURANT_ADMIN, Role.MANAGER)
    assert can_assign_role(Role.MANAGER, Role.CASHIER)
    assert not can_assign_role(Role.MANAGER, Role.MANAGER)
    assert not can_assign_role(Role.MANAGER, Role.RESTAURANT_ADMIN)
    assert not can_assign_role(Role.CASHIER, Role.CASHIER)
    assert not can_assign_role(Role.RESTAURANT_ADMIN, Role.PLATFORM_ADMIN)
    assert not can_assign_role(Role.RESTAURANT_ADMIN, Role.CUSTOMER)


