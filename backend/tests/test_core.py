from datetime import timedelta

import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APIRequestFactory
from tests.conftest import TenantClient as APIClient

from apps.accounts.models import User
from apps.core.idempotency import run_idempotent
from apps.core.models import AuditLog, IdempotencyKey, audit
from apps.core.tenancy import tenant_context

from .conftest import PW, host
from .models import Thing


# ---- tenant-aware models -----------------------------------------------------------------------
def test_default_manager_scopes_to_bound_tenant(world):
    Thing.unscoped.create(restaurant=world["a"], branch=world["a1"], label="a")
    Thing.unscoped.create(restaurant=world["b"], branch=world["b1"], label="b")
    assert Thing.objects.count() == 2  # no tenant bound (platform-level code)
    with tenant_context(world["a"]):
        assert [t.label for t in Thing.objects.all()] == ["a"]
    with tenant_context(world["b"]):
        assert [t.label for t in Thing.objects.all()] == ["b"]


def test_branch_from_other_tenant_rejected(world):
    with pytest.raises(ValidationError):
        Thing(restaurant=world["a"], branch=world["b1"], label="x").save()


def test_restaurant_inferred_from_context_and_required_otherwise(world):
    with tenant_context(world["a"]):
        assert Thing.objects.create(branch=world["a1"], label="ctx").restaurant_id == world["a"].pk
    with pytest.raises(ValidationError):
        Thing(branch=world["a1"], label="none").save()


def test_for_branches_filters(world):
    Thing.unscoped.create(restaurant=world["a"], branch=world["a1"], label="1")
    Thing.unscoped.create(restaurant=world["a"], branch=world["a2"], label="2")
    assert [t.label for t in Thing.objects.for_branches([world["a1"].pk])] == ["1"]


# ---- audit log immutability --------------------------------------------------------------------
def test_audit_log_is_append_only(world):
    entry = audit("test.action", actor=world["admin_a"], restaurant=world["a"])
    with pytest.raises(PermissionError):
        entry.delete()
    entry.action = "tampered"
    with pytest.raises(PermissionError):
        entry.save()
    assert AuditLog.objects.get(pk=entry.pk).action == "test.action"


# ---- idempotency -------------------------------------------------------------------------------
def _request(world):
    req = APIRequestFactory().post("/x")
    req.tenant, req.user = world["a"], world["cashier_a1"]
    return req


def test_idempotent_replay_does_not_repeat_side_effect(world):
    calls = []

    def handler():
        calls.append(1)
        return 201, {"id": len(calls)}

    req = _request(world)
    first = run_idempotent(req, "order.create", "key-1", {"total": "10.00"}, handler)
    second = run_idempotent(req, "order.create", "key-1", {"total": "10.00"}, handler)
    assert first == second == (201, {"id": 1})
    assert len(calls) == 1
    assert IdempotencyKey.objects.count() == 1


def test_idempotency_key_reuse_with_different_payload_rejected(world):
    req = _request(world)
    run_idempotent(req, "payment.init", "k", {"amount": "5.00"}, lambda: (201, {}))
    with pytest.raises(DRFValidationError):
        run_idempotent(req, "payment.init", "k", {"amount": "500.00"}, lambda: (201, {}))


def test_idempotency_scoped_per_tenant_and_user(world):
    req_a = _request(world)
    req_b = _request(world)
    req_b.tenant, req_b.user = world["b"], world["admin_b"]
    run_idempotent(req_a, "op", "same", {}, lambda: (201, {"who": "a"}))
    assert run_idempotent(req_b, "op", "same", {}, lambda: (201, {"who": "b"})) == (201, {"who": "b"})


def test_idempotency_failed_handler_rolls_back_key(world):
    req = _request(world)

    def boom():
        raise RuntimeError("fail")

    with pytest.raises(RuntimeError):
        run_idempotent(req, "op", "kf", {}, boom)
    assert run_idempotent(req, "op", "kf", {}, lambda: (201, {"ok": True})) == (201, {"ok": True})


# ---- authentication ----------------------------------------------------------------------------
def login(slug, email, password):
    return APIClient(HTTP_HOST=host(slug)).post("/api/v1/auth/login/", {"email": email, "password": password}, format="json")


def test_login_success_and_token_works(world):
    r = login("alpha", "admin@a.com", PW)
    assert r.status_code == 200
    c = APIClient(HTTP_HOST=host("alpha"))
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['data']['access']}")
    me = c.get("/api/v1/auth/me/")
    assert me.data["data"]["role"] == "restaurant_admin"


def test_token_from_one_tenant_grants_nothing_in_another(world):
    token = login("alpha", "admin@a.com", PW).data["data"]["access"]
    c = APIClient(HTTP_HOST=host("bravo"))
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert c.get("/api/v1/restaurants/branches/").status_code == 403
    assert c.get("/api/v1/auth/me/").data["data"]["role"] is None


def test_login_requires_membership_in_host_tenant(world):
    assert login("bravo", "admin@a.com", PW).status_code == 401
    assert login(None, "admin@a.com", PW).status_code == 401  # platform host is for platform admins only
    assert login(None, "root@x.com", PW).status_code == 200


def test_login_failures_are_uniform_and_lock_out(world):
    cache.clear()
    wrong = login("alpha", "admin@a.com", "bad-password-1")
    unknown = login("alpha", "nobody@a.com", "bad-password-1")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.data == unknown.data  # no account enumeration
    for _ in range(5):
        login("alpha", "admin@a.com", "bad-password-1")
    assert login("alpha", "admin@a.com", PW).status_code == 429  # locked even with right password
    cache.clear()


def test_inactive_user_and_expired_temp_password_cannot_login(world):
    cache.clear()
    u = world["cust_a"]
    u.must_change_password, u.temp_password_expires_at = True, timezone.now() - timedelta(minutes=1)
    u.save()
    assert login("alpha", "cust@a.com", PW).status_code == 401
    u.is_active = False
    u.save()
    assert login("alpha", "cust@a.com", PW).status_code == 401


def test_forced_password_change_flow(world):
    cache.clear()
    u = world["cashier_a1"]
    u.must_change_password, u.temp_password_expires_at = True, timezone.now() + timedelta(hours=1)
    u.save()
    r = login("alpha", "cash1@a.com", PW)
    assert r.data["data"]["must_change_password"] is True
    c = APIClient(HTTP_HOST=host("alpha"))
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['data']['access']}")
    assert c.post("/api/v1/auth/change-password/", {"current_password": PW, "new_password": "short"}, format="json").status_code == 400
    assert c.post("/api/v1/auth/change-password/", {"current_password": PW, "new_password": PW}, format="json").status_code == 400
    ok = c.post("/api/v1/auth/change-password/", {"current_password": PW, "new_password": "Another-Str0ng-Pass9"}, format="json")
    assert ok.status_code == 200
    u.refresh_from_db()
    assert u.must_change_password is False and u.check_password("Another-Str0ng-Pass9")
    assert "Another" not in "".join(str(m) for m in AuditLog.objects.values_list("metadata", flat=True))


def test_errors_use_envelope_and_hide_internals(world):
    r = APIClient(HTTP_HOST=host("alpha")).get("/api/v1/restaurants/branches/")
    assert r.data["success"] is False and "message" in r.data["error"]


def test_all_success_bodies_use_the_envelope(world):
    import json

    from .conftest import client_for

    raw = client_for(world["admin_a"], "alpha").get("/api/v1/restaurants/branches/")
    body = json.loads(raw.content)
    assert body["success"] is True and "results" in body["data"] and body["data"]["count"] == 2
    body = json.loads(client_for(world["platform"], None).get("/api/v1/platform/plans/").content)
    assert body["success"] is True and body["data"]["count"] == 0


def test_page_size_is_client_adjustable_but_capped(world):
    from apps.tenants.models import Branch

    from .conftest import client_for

    for i in range(30):
        Branch.unscoped.create(restaurant=world["a"], name=f"B{i}", code=f"X{i}")
    c = client_for(world["admin_a"], "alpha")
    assert len(c.get("/api/v1/restaurants/branches/").data["results"]) == 25
    assert len(c.get("/api/v1/restaurants/branches/?page_size=100").data["results"]) == 32
    assert len(c.get("/api/v1/restaurants/branches/?page_size=5000").data["results"]) == 32  # capped at 100, only 32 exist
    assert len(c.get("/api/v1/restaurants/branches/?page_size=10").data["results"]) == 10


def test_cors_preflight_allows_idempotency_key_header(world, settings):
    settings.CORS_ALLOWED_ORIGIN_REGEXES = [r"^http://([a-z0-9-]+\.)?localhost:\d+$"]
    r = APIClient(HTTP_HOST=host("alpha")).options(
        "/api/v1/orders/checkout/", HTTP_ORIGIN="http://alpha.localhost:5173",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST", HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,authorization,idempotency-key")
    assert r.status_code == 200 and "idempotency-key" in r["Access-Control-Allow-Headers"].lower()
