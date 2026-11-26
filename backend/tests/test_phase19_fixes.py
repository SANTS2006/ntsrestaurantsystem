"""Row locks that PostgreSQL accepts, and the platform two-step switch applying to sign-in."""
import pathlib
import re

import pytest

from apps.accounts import mfa
from apps.tenants.models import PlatformSettings

from .conftest import PW, client_for

APPS = pathlib.Path(__file__).resolve().parents[1] / "apps"


def test_no_row_lock_covers_an_optional_join():
    """PostgreSQL refuses FOR UPDATE on the nullable side of an outer join (SQLite, used by tests, does not), which caused a live 500.
    So every locking query that also uses select_related must lock only its own row: select_for_update(of=("self",))."""
    bad = []
    for path in APPS.rglob("*.py"):
        lines = path.read_text(encoding="utf-8").split("\n")
        for i, line in enumerate(lines):
            if not re.search(r"select_for_update\(\)", line):
                continue
            stmt, j = line, i
            while stmt.count("(") > stmt.count(")") and j + 1 < len(lines):
                j += 1
                stmt += lines[j]
            if "select_related(" in stmt:
                bad.append(f"{path.name}:{i + 1}")
    assert not bad, bad


# ------------------------------------------------------------------ the switch applies to sign-in too
def enrol(user):
    secret = mfa.begin_setup(user)
    secret = secret["secret"] if isinstance(secret, dict) else secret
    return secret


def login(email, slug=None):
    from tests.conftest import TenantClient, host

    return TenantClient(HTTP_HOST=host(slug)).post("/api/v1/auth/login/", {"email": email, "password": PW}, format="json")


def test_switching_two_step_off_removes_the_code_step_and_on_brings_it_back(world, settings):
    settings.MFA_ENFORCEMENT = True
    user = world["admin_a"]
    user.mfa_enabled = True
    user.save(update_fields=["mfa_enabled"])
    first = login("admin@a.com", "alpha").json()["data"]
    assert first.get("mfa_required") is True and "access" not in first

    PlatformSettings.load()
    PlatformSettings.objects.filter(pk=1).update(mfa_enforced=False)
    off = login("admin@a.com", "alpha").json()["data"]
    assert "access" in off and "mfa_required" not in off
    from rest_framework.test import APIClient

    c = APIClient(HTTP_HOST="platform.test", HTTP_AUTHORIZATION=f"Bearer {off['access']}")
    me = c.get("/alpha/api/v1/auth/me/").json()["data"]
    assert me["mfa"]["enforced"] is False and me["mfa"]["required"] is False
    assert c.get("/alpha/api/v1/staff/members/").status_code == 200

    PlatformSettings.objects.filter(pk=1).update(mfa_enforced=True)
    again = login("admin@a.com", "alpha").json()["data"]
    assert again.get("mfa_required") is True  # the enrolment was kept
    user.refresh_from_db()
    assert user.mfa_enabled


def test_switch_off_does_not_ask_the_platform_owner_for_a_code_either(world, settings):
    settings.MFA_ENFORCEMENT = True
    root = world["platform"]
    root.mfa_enabled = True
    root.save(update_fields=["mfa_enabled"])
    PlatformSettings.load()
    PlatformSettings.objects.filter(pk=1).update(mfa_enforced=False)
    data = login("root@x.com").json()["data"]
    assert "access" in data
    r = client_for(root).post("/api/v1/platform/settings/mfa/", {"enforced": True, "password": PW}, format="json")
    assert r.status_code == 200  # turning it back on needs the password only while the switch is off


# ------------------------------------------------------------------ mobile money at the till and online
from .test_phase5_orders import checkout, clean, line, shop  # noqa: E402,F401


@pytest.fixture(autouse=True)
def hosted_page(monkeypatch):
    """The stand-in provider has no payment page; give it one, as Monime does."""
    from apps.payments import providers

    real = providers.SimulatedProvider.create_payment

    def create(self, **kw):
        made = real(self, **kw)
        return providers.Created(provider_ref=made.provider_ref, redirect_url=f"https://pay.example.test/{made.provider_ref}")

    monkeypatch.setattr(providers.SimulatedProvider, "create_payment", create)


def momo_shop(world):
    from apps.tenants.models import RestaurantSettings

    RestaurantSettings.objects.filter(restaurant=world["a"]).update(online_payments_enabled=True)


def test_new_restaurants_offer_mobile_money_by_default(db):
    from apps.tenants.models import Restaurant

    assert Restaurant.objects.create(name="N", slug="newplace").get_settings().online_payments_enabled is True


def test_till_mobile_money_returns_a_reopenable_payment_page_and_qr(world, shop, clean):  # noqa: F811
    momo_shop(world)
    c = client_for(world["cashier_a1"], "alpha")
    assert c.post("/api/v1/cashier/shift/open/", {"branch_id": world["a1"].pk, "opening_cash": "10.00"}, format="json").status_code == 201
    body = {"items": [{"product_id": shop["rice"].pk, "quantity": 1}], "fulfilment": "dine_in", "payment": "mobile_money", "payer_phone": "+23276123456"}
    r = c.post("/api/v1/cashier/orders/", body, format="json", HTTP_IDEMPOTENCY_KEY="till-momo-1")
    assert r.status_code == 201, r.data
    pay = r.data["payment"]
    assert pay["status"] == "pending" and pay["checkout_url"] and pay["method"] == "mobile_money"
    st = c.get(f"/api/v1/payments/{pay['id']}/status/")
    assert st.status_code == 200 and st.data["status"] == "pending" and st.data["qr"].startswith("data:image/png;base64,")
    assert st.data["checkout_url"] == pay["checkout_url"]  # survives reloads and blocked pop-ups
    order = c.get(f"/api/v1/orders/manage/{pay['order_id']}/").data
    assert order["payments"][0]["checkout_url"] == pay["checkout_url"]


def test_till_can_take_mobile_money_for_an_unpaid_order_and_other_roles_cannot(world, shop, clean):  # noqa: F811
    momo_shop(world)
    o = checkout(world, [line(shop["rice"], 1)], key="pl1").data
    body = {"order_id": o["id"], "phone": "+23276123456"}
    for who in ("kitchen_a1", "delivery_a1", "cust_a"):
        assert client_for(world[who], "alpha").post("/api/v1/payments/mobile-money/", body, format="json", HTTP_IDEMPOTENCY_KEY=f"k-{who}").status_code == 403
    assert client_for(world["cashier_a2"], "alpha").post("/api/v1/payments/mobile-money/", body, format="json", HTTP_IDEMPOTENCY_KEY="other-branch").status_code == 400
    r = client_for(world["cashier_a1"], "alpha").post("/api/v1/payments/mobile-money/", body, format="json", HTTP_IDEMPOTENCY_KEY="till-pl")
    assert r.status_code == 201 and r.data["checkout_url"]
    again = client_for(world["cashier_a1"], "alpha").post("/api/v1/payments/mobile-money/", body, format="json", HTTP_IDEMPOTENCY_KEY="till-pl-2")
    assert again.data["id"] == r.data["id"] and again.data["checkout_url"] == r.data["checkout_url"]  # no second charge


# ------------------------------------------------------------------ notifications page and detail
def test_notification_detail_shows_the_record_to_those_who_may_see_it(world, shop, clean):  # noqa: F811
    from apps.accounts.models import Membership

    o = checkout(world, [line(shop["rice"], 2)], key="nd1").data
    c = client_for(world["cashier_a1"], "alpha")
    listing = c.get("/api/v1/notifications/?page=1").json()["data"]
    assert listing["count"] >= 1 and listing["has_next"] is False and listing["unread"] >= 1
    nid = next(i["id"] for i in listing["items"] if o["number"] in i["title"])
    d = c.get(f"/api/v1/notifications/{nid}/").json()["data"]
    assert d["read"] is True and d["details"]["heading"] == f"Order {o['number']}"
    assert any("Rice" in i for i in d["details"]["items"]) and any(f["label"] == "Total" for f in d["details"]["fields"])
    assert nid not in [i["id"] for i in c.get("/api/v1/notifications/?page=1&unread=1").json()["data"]["items"]]
    # someone else cannot open it
    assert client_for(world["cashier_a2"], "alpha").get(f"/api/v1/notifications/{nid}/").status_code == 404
    # once moved to another branch, the same person no longer sees the record behind an old notification
    Membership.objects.get(user=world["cashier_a1"], restaurant=world["a"]).branches.set([world["a2"]])
    again = client_for(world["cashier_a1"], "alpha").get(f"/api/v1/notifications/{nid}/").json()["data"]
    assert again["details"] is None and again["title"]


# ------------------------------------------------------------------ search engine metadata
PAGE = ('<!doctype html><html lang="en"><head><title>NTS Restaurant Platform</title>\n    <!--runtime-config-->\n'
        '    <meta name="description" content="default" />\n    <meta property="og:image" content="/logo-512.png" />\n</head><body><div id="root"></div></body></html>')


def page(path, settings, tmp_path):
    from rest_framework.test import APIClient

    (tmp_path / "i.html").write_text(PAGE, encoding="utf-8")
    settings.SPA_INDEX = tmp_path / "i.html"
    return APIClient(HTTP_HOST="platform.test").get(path).content.decode()


def test_public_pages_get_their_own_title_and_metadata(world, shop, settings, tmp_path):  # noqa: F811
    world["a"].city, world["a"].description = "Freetown", 'Great food </script><script>alert(1)</script> "daily"'
    world["a"].save()
    html = page("/alpha", settings, tmp_path)
    assert "<title>Alpha | Freetown</title>" in html and 'rel="canonical" href="http://platform.test/alpha"' in html
    assert '"@type": "Restaurant"' in html and "application/ld+json" in html and "<script>alert(1)" not in html
    assert html.count('name="description"') == 1 and 'content="default"' not in html and "<noscript><h1>Alpha</h1>" in html
    menu = page("/alpha/menu", settings, tmp_path)
    assert "<title>Menu | Alpha</title>" in menu and "<li>Rice</li>" in menu
    dish = page("/alpha/menu/rice", settings, tmp_path)
    assert "<title>Rice | Alpha</title>" in dish and '"@type": "MenuItem"' in dish
    home = page("/", settings, tmp_path)
    assert "Restaurant management and online ordering platform |" in home and '"@type": "SoftwareApplication"' in home


def test_private_and_unknown_pages_are_not_indexed(world, settings, tmp_path):
    for path in ("/alpha/manage/orders", "/alpha/login", "/alpha/checkout", "/alpha/account", "/admin", "/login", "/alpha/menu/no-such-dish"):
        assert 'content="noindex, nofollow"' in page(path, settings, tmp_path), path


def test_platform_sitemap_lists_open_restaurants_and_robots_hides_private_pages(world):
    from rest_framework.test import APIClient

    from apps.tenants.models import Restaurant

    Restaurant.objects.filter(slug="bravo").update(status="suspended")
    c = APIClient(HTTP_HOST="platform.test")
    sm = c.get("/sitemap.xml").content.decode()
    assert "<loc>http://platform.test/alpha/menu</loc>" in sm and "bravo" not in sm
    assert "Disallow: /*/manage" in c.get("/robots.txt").content.decode()
