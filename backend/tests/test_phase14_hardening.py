"""Phase 14: security sweeps, query-count (N+1) budgets, input fuzzing and a performance smoke test."""
import re
import time
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone
from tests.conftest import TenantClient as APIClient

from apps.orders.models import Order
from apps.payments.models import Payment

from .conftest import client_for, host
from .test_phase5_orders import clean, shop  # noqa: F401  (fixtures)
from .test_phase8_management import mk_order

# Routes that are public by design (still validated, throttled or signature-checked). Anything else must refuse anonymous callers.
PUBLIC = [
    r"^healthz$", r"^readyz$", r"^robots\.txt$", r"^sitemap\.xml$", r"^api/schema/", r"^api/docs/",
    r"^api/v1/auth/(register|login|refresh|token/refresh|mfa/verify|password-reset|verify-email|resend-verification|forgot-password|reset-password|google|setup-password|logout)/?",
    r"^api/v1/platform/public/", r"^api/v1/restaurants/current/", r"^api/v1/catalog/public/",
    r"^api/v1/catering/public/", r"^api/v1/floor/public/", r"^api/v1/qr-menu/public/", r"^api/v1/orders/(quote|checkout)/",
    r"^api/v1/payments/(webhooks|simulate|public)", r"^api/v1/system/health", r"^api/v1/system/cron/",  # system is platform-admin only: checked separately
]
SKIP = [r"^django-admin/"]
CONVERTERS = {"int": "1", "str": "x", "slug": "x", "uuid": str(uuid.uuid4()), "path": "x"}


def routes(patterns=None, prefix=""):
    for p in patterns if patterns is not None else get_resolver().url_patterns:
        piece = str(p.pattern)
        if isinstance(p, URLResolver):
            yield from routes(p.url_patterns, prefix + piece)
        elif isinstance(p, URLPattern):
            yield prefix + piece


def concrete(route):
    r = route.lstrip("^")
    if "format_suffix" in r or "<format>" in r:
        return None
    r = re.sub(r"<(\w+):\w+>", lambda m: CONVERTERS.get(m.group(1), "x"), r)
    r = re.sub(r"\(\?P<\w+>[^)]*\)", "1", r)
    r = re.sub(r"\(\?:[^)]*\)\??", "", r)
    r = r.replace("\\.", ".").replace("$", "").replace("?", "")
    if re.search(r"[\[\](){}*+|\\]", r):
        return None
    return "/" + r


def all_urls():
    seen = {}
    for route in routes():
        if any(re.search(s, route.lstrip("^")) for s in SKIP):
            continue
        url = concrete(route)
        if url and url not in seen:
            seen[url] = route
    return seen


def is_public(route):
    return any(re.search(p, route.lstrip("^")) for p in PUBLIC)


def test_route_inventory_is_large_enough_to_mean_something():
    assert len(all_urls()) > 120


@pytest.mark.parametrize("hostname", [host("alpha"), host()])
def test_every_non_public_route_refuses_anonymous_callers(world, hostname):
    c = APIClient(HTTP_HOST=hostname)
    bad = []
    for url, route in all_urls().items():
        if is_public(route):
            continue
        for method in ("get", "post", "patch", "put", "delete"):
            r = getattr(c, method)(url, {}, format="json")
            if r.status_code not in (401, 403, 404, 405):
                bad.append((method.upper(), url, r.status_code))
    assert not bad, bad[:15]


@pytest.mark.parametrize("hostname", [host("alpha"), host()])
def test_no_route_ever_returns_a_server_error_for_anonymous_or_garbage_input(world, hostname):
    c = APIClient(HTTP_HOST=hostname)
    errors = []
    for url in all_urls():
        for method, body in (("get", None), ("post", {}), ("post", {"x": "y" * 5000, "id": -1, "items": "nope"}), ("patch", [1, 2])):
            r = getattr(c, method)(url, body, format="json")
            if r.status_code >= 500:
                errors.append((method.upper(), url, r.status_code))
    assert not errors, errors[:15]


def test_authenticated_garbage_never_causes_a_server_error(world):
    errors = []
    for who, slug in (("admin_a", "alpha"), ("mgr_a1", "alpha"), ("cashier_a1", "alpha"), ("cust_a", "alpha"), ("platform", None)):
        c = client_for(world[who], slug)
        for url in all_urls():
            for method, body in (("get", None), ("post", {}), ("post", {"amount": "NaN", "items": [{"product": "x"}], "id": 10**30}), ("patch", {"name": None})):
                r = getattr(c, method)(url, body, format="json")
                if r.status_code >= 500:
                    errors.append((who, method.upper(), url, r.status_code))
    assert not errors, errors[:15]


# ---------------- headers, CORS, tokens ----------------
def test_security_headers_and_no_cache_on_private_data(world):
    r = client_for(world["admin_a"], "alpha").get("/api/v1/payroll/employees/")
    assert r["X-Content-Type-Options"] == "nosniff" and r["X-Frame-Options"] == "DENY"
    assert r["Referrer-Policy"] == "same-origin"
    assert "Server" not in r or "gunicorn" not in r["Server"].lower()


def test_cors_allows_only_configured_origins(world, settings):
    c = APIClient(HTTP_HOST=host("alpha"))
    evil = c.options("/api/v1/auth/login/", HTTP_ORIGIN="https://evil.example", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
    assert "Access-Control-Allow-Origin" not in evil


def test_tampered_and_foreign_tokens_are_rejected(world):
    from apps.accounts.services import issue_tokens

    tok = issue_tokens(world["admin_a"])["access"]
    c = APIClient(HTTP_HOST=host("alpha"))
    head, body, sig = tok.split(".")
    for bad in (f"{head}.{body}.{sig[:-3]}abc", f"{head}.{body}x.{sig}", "garbage", "", f"{head}.{body}."):
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {bad}")
        assert c.get("/api/v1/payroll/employees/").status_code == 401
    # an alpha administrator's valid token gives no access on another restaurant's host
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")
    assert c.get("/api/v1/payroll/employees/").status_code == 200
    c2 = APIClient(HTTP_HOST=host("bravo"))
    c2.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")
    assert c2.get("/api/v1/payroll/employees/").status_code in (401, 403, 404)


def test_unknown_and_malformed_hosts_do_not_reach_tenant_data(world):
    for h in ("unknown.platform.test", "evil.example.com", "alpha.platform.test.evil.com", "..platform.test"):
        r = client_for(world["admin_a"]).get("/api/v1/payroll/employees/", HTTP_HOST=h)
        assert r.status_code in (400, 401, 403, 404), (h, r.status_code)


# ---------------- pagination and filter fuzzing ----------------
@pytest.mark.parametrize("params", [{"page": "abc"}, {"page": "-1"}, {"page": "999999"}, {"page_size": "100000"}, {"page_size": "-5"}, {"page_size": "x"}])
def test_pagination_inputs_are_safe_and_bounded(world, shop, clean, params):  # noqa: F811
    for i in range(3):
        mk_order(world, world["a1"], "10.00", paid="10.00")
    r = client_for(world["admin_a"], "alpha").get("/api/v1/orders/manage/", params)
    assert r.status_code in (200, 404), r.content
    if r.status_code == 200:
        assert len(r.data["results"]) <= 100


# ---------------- query budgets: counts must not grow with data (N+1 detector) ----------------
def count_queries(client, url):
    with CaptureQueriesContext(connection) as ctx:
        r = client.get(url)
    assert r.status_code == 200, (url, r.status_code, r.content[:200])
    return len(ctx)


def grow(world, n, start=0):
    for i in range(n):
        mk_order(world, world["a1"] if i % 2 else world["a2"], f"{10 + i}.00", paid=f"{10 + i}.00", item=f"Dish {start + i}", qty=2, source="cashier" if i % 3 else "online",
                 cashier=world["cashier_a1"], days_ago=i % 20)


URLS = [
    ("admin_a", "/api/v1/orders/manage/"), ("admin_a", "/api/v1/reports/branch/"), ("admin_a", "/api/v1/reports/finance/"), ("admin_a", "/api/v1/reports/analytics/"),
    ("admin_a", "/api/v1/reports/audit/"), ("admin_a", "/api/v1/payroll/employees/"), ("admin_a", "/api/v1/payroll/periods/"), ("admin_a", "/api/v1/payroll/summary/"),
    ("mgr_a1", "/api/v1/orders/manage/"), ("mgr_a1", "/api/v1/reports/branch/"), ("admin_a", "/api/v1/catalog/products/"), ("admin_a", "/api/v1/staff/members/"),
    ("admin_a", "/api/v1/catering/requests/"), ("admin_a", "/api/v1/restaurants/branches/"),
]


@pytest.mark.parametrize("who,url", URLS)
def test_query_count_does_not_grow_with_data(world, shop, clean, who, url):  # noqa: F811
    grow(world, 4)
    c = client_for(world[who], "alpha")
    c.get(url)  # warm caches (content types, settings)
    small = count_queries(c, url)
    grow(world, 20, start=4)
    big = count_queries(c, url)
    assert big <= small + 2, f"{url}: {small} queries with 4 orders, {big} with 24 (N+1?)"
    assert big < 60, f"{url} runs {big} queries"


def test_public_menu_query_budget(world, shop, clean):  # noqa: F811
    c = APIClient(HTTP_HOST=host("alpha"))
    c.get("/api/v1/catalog/public/menu/")
    n = count_queries(c, "/api/v1/catalog/public/menu/")
    assert n < 25, n


# ---------------- performance smoke (generous bounds; catches accidental O(n^2) or missing indexes) ----------------
def test_reports_stay_fast_with_a_few_thousand_orders(world, shop, clean):  # noqa: F811
    now = timezone.now()
    orders = [Order(restaurant=world["a"], branch=world["a1"] if i % 2 else world["a2"], number=f"BULK-{i:06d}", source="online", status="completed",
                    fulfilment="pickup", payment_method="cash", payment_status="paid", contact_name="x", contact_phone="0", currency="USD",
                    subtotal=Decimal("25.00"), total=Decimal("25.00"), amount_paid=Decimal("25.00")) for i in range(3000)]
    Order.unscoped.bulk_create(orders, batch_size=500)
    Order.unscoped.filter(number__startswith="BULK-").update(created_at=now - timedelta(days=3))
    pays = [Payment(restaurant=world["a"], branch=o.branch, order=o, reference=f"BP-{o.pk}", provider="cash", method="cash", status="succeeded", amount=Decimal("25.00"),
                    currency="USD", paid_at=now - timedelta(days=3)) for o in Order.unscoped.filter(number__startswith="BULK-")]
    Payment.unscoped.bulk_create(pays, batch_size=500)
    c = client_for(world["admin_a"], "alpha")
    for url in ("/api/v1/reports/branch/", "/api/v1/reports/finance/", "/api/v1/reports/analytics/", "/api/v1/orders/manage/", "/api/v1/reports/export/?type=orders"):
        t = time.perf_counter()
        r = c.get(url)
        dt = time.perf_counter() - t
        assert r.status_code == 200 and dt < 5, (url, dt)
    assert c.get("/api/v1/reports/finance/").data["income"]["collected"] == "75000.00"


# ---------------- operational commands ----------------
def test_concurrency_check_refuses_unsafe_use(db):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="understand"):
        call_command("concurrency_check")
    with pytest.raises(CommandError, match="PostgreSQL"):
        call_command("concurrency_check", confirmed=True)


def test_preflight_fails_a_development_configuration_and_never_prints_secrets(db, settings, capsys):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    settings.BREVO_API_KEY = "super-secret-brevo-value"
    with pytest.raises(CommandError, match="Preflight failed"):
        call_command("preflight")
    out = capsys.readouterr().out
    assert "FAIL" in out and "Database is PostgreSQL" in out and "Redis is configured" in out
    assert "super-secret-brevo-value" not in out and settings.SECRET_KEY not in out
