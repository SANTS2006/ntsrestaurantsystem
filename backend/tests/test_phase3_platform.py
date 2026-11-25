import io
import re

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from tests.conftest import TenantClient as APIClient

from apps.accounts.models import Membership, Role, User
from apps.core.models import AuditLog
from apps.notifications.providers import ConsoleProvider
from apps.tenants.models import Branch, PlatformSettings, Restaurant, SubscriptionPlan

from .conftest import PW, client_for, host

R = "/api/v1/platform/restaurants/"
NEW_PW = "Another-Str0ng-Pass9"


@pytest.fixture(autouse=True)
def clean(db, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    ConsoleProvider.outbox.clear()
    cache.clear()


def png(name="logo.png", fmt="PNG", size=(8, 8)):
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


def payload(**over):
    return {"name": "Ocean View Restaurant", "slug": "ocean-view", "admin_full_name": "Olive Owner",
            "admin_email": "olive@ocean.com", "primary_color": "#0e7490", "secondary_color": "#164e63",
            "contact_email": "hello@ocean.com", "contact_phone": "+23276000000", "description": "Seafood by the bay",
            "city": "Freetown", "country": "Sierra Leone", **over}


def plat(world):
    return client_for(world["platform"], None)


# ---- registration workflow ---------------------------------------------------------------------
def test_registration_runs_full_onboarding_workflow(world):
    r = plat(world).post(R, payload(logo=png()), format="multipart")
    assert r.status_code == 201, r.data
    rest = Restaurant.objects.get(slug="ocean-view")
    assert rest.status == "active" and rest.logo and rest.logo.name.startswith("restaurants/logos/")
    assert rest.settings and Branch.unscoped.filter(restaurant=rest, code="MAIN").exists()
    admin = User.objects.get(email="olive@ocean.com")
    assert Membership.objects.get(user=admin, restaurant=rest).role == Role.RESTAURANT_ADMIN
    assert not admin.has_usable_password()  # no predictable bootstrap password
    mail = ConsoleProvider.outbox[-1]
    assert mail["to"] == "olive@ocean.com" and "olive@ocean.com" in mail["html"]
    assert "http://platform.test/ocean-view/login" in mail["html"] and "must set your own password" in mail["html"]
    assert mail["sender_name"] != "Ocean View Restaurant"  # platform-originated mail
    assert AuditLog.objects.filter(action="restaurant.registered", restaurant=rest).exists()
    assert r.data["data"]["public_url"] == "http://platform.test/ocean-view"
    # the admin completes onboarding and signs in on the new tenant host
    token = re.search(r"token=([\w-]+)", mail["html"]).group(1)
    api = APIClient(HTTP_HOST=host("ocean-view"))
    assert api.post("/api/v1/auth/setup-password/", {"token": token, "password": NEW_PW}, format="json").status_code == 200
    login = api.post("/api/v1/auth/login/", {"email": "olive@ocean.com", "password": NEW_PW}, format="json")
    assert login.status_code == 200
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['data']['access']}")
    assert api.get("/api/v1/auth/me/").data["data"]["role"] == "restaurant_admin"
    assert len(api.get("/api/v1/restaurants/branches/").data["results"]) == 1


@pytest.mark.parametrize("over", [
    {"slug": "alpha"}, {"slug": "admin"}, {"slug": "Bad Slug"}, {"slug": "-x"},
    {"primary_color": "red"}, {"secondary_color": "#12345"}, {"admin_email": "not-an-email"}, {"name": ""},
])
def test_registration_validation(world, over):
    n = Restaurant.objects.count()
    assert plat(world).post(R, payload(**over), format="json").status_code == 400
    assert Restaurant.objects.count() == n


@pytest.mark.parametrize("make", [
    lambda: SimpleUploadedFile("x.png", b"not an image", content_type="image/png"),
    lambda: SimpleUploadedFile("x.svg", b"<svg onload=alert(1)/>", content_type="image/svg+xml"),
    lambda: png("x.gif", "GIF"),
])
def test_logo_rejects_non_images_svg_and_other_formats(world, make):
    assert plat(world).post(R, payload(logo=make()), format="multipart").status_code == 400
    assert not Restaurant.objects.filter(slug="ocean-view").exists()


def test_logo_size_limit(world, monkeypatch):
    monkeypatch.setattr("apps.tenants.platform_serializers.LOGO_MAX_BYTES", 10)
    assert plat(world).post(R, payload(logo=png()), format="multipart").status_code == 400


def test_registration_rolls_back_when_admin_cannot_be_created(world):
    r = plat(world).post(R, payload(admin_email="root@x.com"), format="json")  # a platform admin's email
    assert r.status_code == 400
    assert not Restaurant.objects.filter(slug="ocean-view").exists()
    assert not Branch.unscoped.filter(code="MAIN", restaurant__slug="ocean-view").exists()


def test_existing_verified_user_becomes_admin_without_password_change(world):
    r = plat(world).post(R, payload(admin_email="admin@a.com"), format="json")
    assert r.status_code == 201
    assert "setup-password" not in ConsoleProvider.outbox[-1]["html"]
    c = APIClient(HTTP_HOST=host("ocean-view"))
    assert c.post("/api/v1/auth/login/", {"email": "admin@a.com", "password": PW}, format="json").status_code == 200


# ---- access control ----------------------------------------------------------------------------
ENDPOINTS = [("get", R), ("post", R), ("get", "/api/v1/platform/dashboard/"), ("get", "/api/v1/platform/settings/"),
             ("patch", "/api/v1/platform/settings/"), ("get", "/api/v1/platform/plans/"),
             ("get", "/api/v1/platform/audit-logs/")]


@pytest.mark.parametrize("who", ["admin_a", "mgr_a1", "cashier_a1", "cust_a"])
@pytest.mark.parametrize("method,url", ENDPOINTS)
def test_non_platform_users_forbidden_everywhere(world, who, method, url):
    for slug in (None, "alpha"):
        assert getattr(client_for(world[who], slug), method)(url, {}, format="json").status_code == 403


@pytest.mark.parametrize("method,url", ENDPOINTS)
def test_anonymous_unauthorised(world, method, url):
    assert getattr(APIClient(HTTP_HOST=host()), method)(url, {}, format="json").status_code == 401


def test_platform_admin_endpoints_not_served_on_tenant_hosts(world):
    assert client_for(world["platform"], "alpha").get(R).status_code == 403


def test_restaurants_cannot_be_deleted(world):
    assert plat(world).delete(f"{R}{world['a'].pk}/").status_code == 405


# ---- listing, editing, suspension --------------------------------------------------------------
def test_list_search_filter_and_counts(world):
    c = plat(world)
    r = c.get(R)
    assert r.status_code == 200 and r.data["count"] == 2
    alpha = next(x for x in r.data["results"] if x["slug"] == "alpha")
    assert (alpha["branches_count"], alpha["staff_count"], alpha["customers_count"]) == (2, 7, 2)
    assert [x["slug"] for x in c.get(R, {"q": "brav"}).data["results"]] == ["bravo"]
    c.post(f"{R}{world['b'].pk}/suspend/", {}, format="json")
    assert [x["slug"] for x in c.get(R, {"status": "suspended"}).data["results"]] == ["bravo"]


def test_edit_branding_but_not_status(world):
    c = plat(world)
    r = c.patch(f"{R}{world['a'].pk}/", {"primary_color": "#112233", "name": "Alpha Grill", "status": "suspended"}, format="json")
    assert r.status_code == 200
    world["a"].refresh_from_db()
    assert world["a"].primary_color == "#112233" and world["a"].name == "Alpha Grill" and world["a"].status == "active"
    assert c.patch(f"{R}{world['a'].pk}/", {"primary_color": "bad"}, format="json").status_code == 400
    assert c.patch(f"{R}{world['a'].pk}/", {"slug": "bravo"}, format="json").status_code == 400  # uniqueness
    assert AuditLog.objects.filter(action="restaurant.updated", restaurant=world["a"]).exists()


def test_suspend_blocks_tenant_and_activate_restores(world):
    c = plat(world)
    assert c.post(f"{R}{world['a'].pk}/suspend/", {"reason": "unpaid"}, format="json").data["data"]["status"] == "suspended"
    assert APIClient(HTTP_HOST=host("alpha")).get("/api/v1/restaurants/current/").status_code == 403
    assert APIClient(HTTP_HOST=host("bravo")).get("/api/v1/restaurants/current/").status_code == 200  # others unaffected
    log = AuditLog.objects.get(action="restaurant.suspended")
    assert log.metadata["reason"] == "unpaid" and log.actor == world["platform"]
    assert c.post(f"{R}{world['a'].pk}/activate/", {}, format="json").data["data"]["status"] == "active"
    assert APIClient(HTTP_HOST=host("alpha")).get("/api/v1/restaurants/current/").status_code == 200


# ---- settings, plans, dashboard, audit ---------------------------------------------------------
def test_whatsapp_setting_roundtrip_and_validation(world):
    c = plat(world)
    assert c.patch("/api/v1/platform/settings/", {"whatsapp_number": "abc"}, format="json").status_code == 400
    assert c.patch("/api/v1/platform/settings/", {"whatsapp_number": "+23276123456"}, format="json").status_code == 200
    pub = APIClient(HTTP_HOST=host())
    assert pub.get("/api/v1/platform/public/settings/").data["data"]["whatsapp_number"] == "23276123456"


def test_plans_public_lists_only_active_and_admin_manages(world):
    c = plat(world)
    r = c.post("/api/v1/platform/plans/", {"name": "Starter", "slug": "starter", "price": "19.99", "features": ["1 branch"]}, format="json")
    assert r.status_code == 201 and r.data["price"] == "19.99"
    c.post("/api/v1/platform/plans/", {"name": "Hidden", "slug": "hidden", "price": "5.00", "is_active": False}, format="json")
    pub = APIClient(HTTP_HOST=host()).get("/api/v1/platform/public/plans/").data["data"]
    assert [p["slug"] for p in pub] == ["starter"]
    assert c.post("/api/v1/platform/plans/", {"name": "Bad", "slug": "bad", "price": "1", "features": "nope"}, format="json").status_code == 400
    assert c.delete(f"/api/v1/platform/plans/{r.data['id']}/").status_code == 405
    assert c.patch(f"/api/v1/platform/plans/{r.data['id']}/", {"is_active": False}, format="json").status_code == 200
    assert APIClient(HTTP_HOST=host()).get("/api/v1/platform/public/plans/").data["data"] == []


def test_dashboard_counts_are_real(world):
    d = plat(world).get("/api/v1/platform/dashboard/").data["data"]
    assert d == {"restaurants_total": 2, "restaurants_active": 2, "restaurants_suspended": 0, "branches_total": 3,
                 "customers_total": 2, "employees_total": 8}


def test_audit_log_listing_and_filters(world):
    c = plat(world)
    c.post(f"{R}{world['a'].pk}/suspend/", {}, format="json")
    c.post(f"{R}{world['b'].pk}/suspend/", {}, format="json")
    r = c.get("/api/v1/platform/audit-logs/", {"action": "restaurant.suspended", "restaurant": world["b"].pk})
    assert r.data["count"] == 1 and r.data["results"][0]["actor_email"] == "root@x.com"
