import time

import pytest
from django.core.cache import cache
from tests.conftest import TenantClient as APIClient

from apps.accounts import mfa
from apps.accounts.models import MFADevice, RecoveryCode, User
from apps.core.models import AuditLog

from .conftest import PW, host

A = "/api/v1/auth/"


@pytest.fixture(autouse=True)
def on(settings, db):
    settings.MFA_ENFORCEMENT = True
    cache.clear()


def client(slug="alpha", token=None):
    c = APIClient(HTTP_HOST=host(slug))
    if token:
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return c


def login(email, slug="alpha", password=PW):
    return client(slug).post(A + "login/", {"email": email, "password": password}, format="json")


def enrol(world, email="admin@a.com", slug="alpha"):
    d = login(email, slug).json()["data"]
    c = client(slug, d["access"])
    s = c.post(A + "mfa/setup/", {"password": PW}, format="json").json()["data"]
    code = mfa.totp_at(s["secret"])
    r = c.post(A + "mfa/confirm/", {"code": code}, format="json")
    assert r.status_code == 200, r.content
    return s["secret"], r.json()["data"]


# ---------------- RFC 6238 ----------------
def test_totp_matches_the_rfc_6238_test_vectors():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # ASCII "12345678901234567890"
    for when, expected in ((59, "287082"), (1111111109, "081804"), (1111111111, "050471"), (1234567890, "005924"), (2000000000, "279037")):
        assert mfa.totp_at(secret, when) == expected
    assert mfa.match_step(secret, "287082", when=59) == 1
    assert mfa.match_step(secret, "287082", when=59 + 30) == 1  # one step of drift allowed
    assert mfa.match_step(secret, "287082", when=59 + 90) is None
    for bad in ("", "12345", "abcdef", "2870820", None):
        assert mfa.match_step(secret, bad, when=59) is None


# ---------------- enrolment gate ----------------
def test_unenrolled_privileged_accounts_can_only_reach_enrolment(world):
    d = login("admin@a.com").json()["data"]
    assert "access" in d and "mfa_required" not in d
    c = client(token=d["access"])
    r = c.get("/api/v1/payroll/employees/")
    assert r.status_code == 403 and r.json()["error"]["code"] == "mfa_enrollment_required"
    assert c.get(A + "me/").json()["data"]["mfa"] == {"enabled": False, "required": True, "enforced": True, "challenge": False, "switched_on": True}
    assert c.get(A + "mfa/status/").status_code == 200
    # a manager or customer is not forced
    for email in ("mgr1@a.com", "cust@a.com"):
        t = login(email).json()["data"]["access"]
        assert client(token=t).get(A + "me/").status_code == 200
    assert client(token=login("mgr1@a.com").json()["data"]["access"]).get("/api/v1/orders/manage/").status_code == 200


def test_platform_admin_is_always_privileged(world):
    t = login("root@x.com", None).json()["data"]["access"]
    c = client(None, t)
    assert c.get("/api/v1/platform/dashboard/").status_code == 403
    assert c.get("/api/v1/platform/dashboard/").json()["error"]["code"] == "mfa_enrollment_required"


def test_enforcement_can_be_switched_off(world, settings):
    settings.MFA_ENFORCEMENT = False
    t = login("admin@a.com").json()["data"]["access"]
    assert client(token=t).get("/api/v1/payroll/employees/").status_code == 200


def test_required_roles_are_configurable(world, settings):
    settings.MFA_REQUIRED_ROLES = ("restaurant_admin", "manager")
    t = login("mgr1@a.com").json()["data"]["access"]
    assert client(token=t).get("/api/v1/orders/manage/").status_code == 403


# ---------------- enrolment ----------------
def test_setup_needs_the_password_and_nothing_is_active_until_confirmed(world):
    d = login("admin@a.com").json()["data"]
    c = client(token=d["access"])
    assert c.post(A + "mfa/setup/", {"password": "wrong"}, format="json").status_code == 403
    assert c.post(A + "mfa/setup/", {}, format="json").status_code == 403
    s = c.post(A + "mfa/setup/", {"password": PW}, format="json").json()["data"]
    assert s["otpauth_uri"].startswith("otpauth://totp/") and s["qr"].startswith("data:image/png;base64,") and len(s["secret"]) >= 32
    assert User.objects.get(email="admin@a.com").mfa_enabled is False
    assert login("admin@a.com").json()["data"].get("mfa_required") is None  # still password-only
    assert c.post(A + "mfa/confirm/", {"code": "000000"}, format="json").status_code == 400
    assert c.post(A + "mfa/confirm/", {"code": mfa.totp_at(s["secret"])}, format="json").status_code == 200
    dev = MFADevice.objects.get()
    assert s["secret"] not in dev.secret_enc  # encrypted at rest
    assert User.objects.get(email="admin@a.com").mfa_enabled is True
    assert c.post(A + "mfa/setup/", {"password": PW}, format="json").status_code == 400  # already on


def test_confirm_returns_ten_recovery_codes_and_tokens_that_lift_the_gate(world):
    _, data = enrol(world)
    assert len(data["recovery_codes"]) == 10 and len(set(data["recovery_codes"])) == 10
    assert RecoveryCode.objects.count() == 10 and all(len(r.code_hash) == 64 for r in RecoveryCode.objects.all())
    assert all(c not in r.code_hash for c in data["recovery_codes"] for r in RecoveryCode.objects.all())
    assert client(token=data["access"]).get("/api/v1/payroll/employees/").status_code == 200
    assert {"auth.mfa_setup_started", "auth.mfa_enabled"} <= set(AuditLog.objects.values_list("action", flat=True))


# ---------------- sign-in with a second factor ----------------
def test_password_alone_never_gives_a_session_once_enrolled(world):
    secret, _ = enrol(world)
    d = login("admin@a.com").json()["data"]
    assert d["mfa_required"] is True and d["mfa_token"] and "access" not in d and "refresh" not in d
    c = client()
    assert c.post(A + "mfa/verify/", {"mfa_token": d["mfa_token"], "code": "123456"}, format="json").status_code == 401
    assert c.post(A + "mfa/verify/", {"mfa_token": "garbage", "code": mfa.totp_at(secret)}, format="json").status_code == 401
    ok = c.post(A + "mfa/verify/", {"mfa_token": d["mfa_token"], "code": mfa.totp_at(secret, time.time() + 30)}, format="json")  # next step: not the one used at enrolment
    assert ok.status_code == 200 and ok.json()["data"]["access"]
    assert client(token=ok.json()["data"]["access"]).get("/api/v1/payroll/employees/").status_code == 200
    assert login("admin@a.com", password="wrong").status_code == 401  # password still checked first


def test_a_code_cannot_be_used_twice(world):
    secret, _ = enrol(world)
    code = mfa.totp_at(secret, time.time() + 30)
    t1 = login("admin@a.com").json()["data"]["mfa_token"]
    assert client().post(A + "mfa/verify/", {"mfa_token": t1, "code": code}, format="json").status_code == 200
    t2 = login("admin@a.com").json()["data"]["mfa_token"]
    assert client().post(A + "mfa/verify/", {"mfa_token": t2, "code": code}, format="json").status_code == 401  # replay


def test_recovery_codes_work_once_each(world):
    secret, data = enrol(world)
    rc = data["recovery_codes"][0]
    t = login("admin@a.com").json()["data"]["mfa_token"]
    r = client().post(A + "mfa/verify/", {"mfa_token": t, "recovery_code": rc}, format="json")
    assert r.status_code == 200 and r.json()["data"]["recovery_codes_left"] == 9
    t = login("admin@a.com").json()["data"]["mfa_token"]
    assert client().post(A + "mfa/verify/", {"mfa_token": t, "recovery_code": rc}, format="json").status_code == 401
    assert client().post(A + "mfa/verify/", {"mfa_token": t, "recovery_code": data["recovery_codes"][1].upper()}, format="json").status_code == 200  # case-insensitive
    assert "auth.mfa_recovery_used" in set(AuditLog.objects.values_list("action", flat=True))


def test_repeated_wrong_codes_lock_the_account(world):
    secret, _ = enrol(world)
    t = login("admin@a.com").json()["data"]["mfa_token"]
    for _ in range(5):
        assert client().post(A + "mfa/verify/", {"mfa_token": t, "code": "000000"}, format="json").status_code == 401
    r = client().post(A + "mfa/verify/", {"mfa_token": t, "code": mfa.totp_at(secret, time.time() + 30)}, format="json")
    assert r.status_code == 429  # even the right code is refused while locked


def test_login_token_expires(world, monkeypatch):
    secret, _ = enrol(world)
    t = login("admin@a.com").json()["data"]["mfa_token"]
    monkeypatch.setattr(mfa, "LOGIN_TOKEN_TTL", -1)
    assert client().post(A + "mfa/verify/", {"mfa_token": t, "code": mfa.totp_at(secret, time.time() + 30)}, format="json").status_code == 401


def test_login_token_dies_when_credentials_are_revoked(world):
    secret, _ = enrol(world)
    t = login("admin@a.com").json()["data"]["mfa_token"]
    User.objects.filter(email="admin@a.com").update(token_version=99)
    assert client().post(A + "mfa/verify/", {"mfa_token": t, "code": mfa.totp_at(secret, time.time() + 30)}, format="json").status_code == 401


# ---------------- management ----------------
def test_required_roles_cannot_switch_mfa_off_but_others_can(world, settings):
    secret, data = enrol(world)
    c = client(token=data["access"])
    r = c.post(A + "mfa/disable/", {"password": PW, "code": mfa.totp_at(secret, time.time() + 30)}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "required"
    settings.MFA_REQUIRED_ROLES = ("restaurant_admin", "manager")
    s2, d2 = enrol(world, "mgr1@a.com")
    settings.MFA_REQUIRED_ROLES = ("restaurant_admin",)
    c2 = client(token=d2["access"])
    assert c2.post(A + "mfa/disable/", {"password": "bad", "code": mfa.totp_at(s2, time.time() + 30)}, format="json").status_code == 403
    assert c2.post(A + "mfa/disable/", {"password": PW, "code": "000000"}, format="json").status_code == 400
    ok = c2.post(A + "mfa/disable/", {"password": PW, "code": mfa.totp_at(s2, time.time() + 30)}, format="json")
    assert ok.status_code == 200 and not User.objects.get(email="mgr1@a.com").mfa_enabled
    assert c2.get(A + "me/").status_code == 401  # sessions were revoked
    assert MFADevice.objects.filter(user__email="mgr1@a.com").count() == 0


def test_regenerating_recovery_codes_replaces_the_old_ones(world):
    secret, data = enrol(world)
    c = client(token=data["access"])
    assert c.post(A + "mfa/recovery-codes/", {"password": PW, "code": "000000"}, format="json").status_code == 400
    r = c.post(A + "mfa/recovery-codes/", {"password": PW, "code": mfa.totp_at(secret, time.time() + 30)}, format="json")
    new = r.json()["data"]["recovery_codes"]
    assert len(new) == 10 and not set(new) & set(data["recovery_codes"])
    t = login("admin@a.com").json()["data"]["mfa_token"]
    assert client().post(A + "mfa/verify/", {"mfa_token": t, "recovery_code": data["recovery_codes"][0]}, format="json").status_code == 401


def test_platform_admin_can_reset_a_staff_members_second_factor(world):
    enrol(world)
    admin_id = User.objects.get(email="admin@a.com").pk
    root = login("root@x.com", None).json()["data"]["access"]
    # the platform admin is gated until enrolled, so enrol first
    pc = client(None, root)
    s = pc.post(A + "mfa/setup/", {"password": PW}, format="json").json()["data"]
    tok = pc.post(A + "mfa/confirm/", {"code": mfa.totp_at(s["secret"])}, format="json").json()["data"]["access"]
    pc = client(None, tok)
    assert pc.post(A + f"mfa/reset/{admin_id}/").status_code == 200
    u = User.objects.get(pk=admin_id)
    assert not u.mfa_enabled and not MFADevice.objects.filter(user=u).exists()
    assert login("admin@a.com").json()["data"].get("mfa_required") is None  # must enrol again
    root_id = User.objects.get(email="root@x.com").pk
    assert pc.post(A + f"mfa/reset/{root_id}/").status_code == 404  # never itself
    other = User.objects.create_user("other-root@x.com", PW, is_platform_admin=True, email_verified=True)
    assert pc.post(A + f"mfa/reset/{other.pk}/").status_code == 403  # another platform admin: operator only
    assert pc.post(A + f"mfa/reset/{User.objects.get(email='cust@a.com').pk}/").status_code == 404  # customers have no second factor to reset
    ac = client(token=login("admin@a.com").json()["data"]["access"])
    assert ac.post(A + f"mfa/reset/{admin_id}/").status_code == 403  # restaurant admins cannot reset anyone
    assert "auth.mfa_reset_by_admin" in set(AuditLog.objects.values_list("action", flat=True))


def test_operator_command_resets_and_revokes(world):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    enrol(world)
    before = User.objects.get(email="admin@a.com").token_version
    call_command("mfa_reset", "admin@a.com")
    u = User.objects.get(email="admin@a.com")
    assert not u.mfa_enabled and u.token_version == before + 1
    with pytest.raises(CommandError):
        call_command("mfa_reset", "nobody@a.com")


def test_two_factor_endpoints_require_authentication(world):
    c = client()
    for path in ("status/", "setup/", "confirm/", "disable/", "recovery-codes/"):
        assert c.post(A + "mfa/" + path).status_code in (401, 405) or c.get(A + "mfa/" + path).status_code == 401
    assert c.post(A + "mfa/reset/1/").status_code in (401, 403)


def test_google_sign_in_for_an_enrolled_account_also_needs_the_second_factor(world, monkeypatch):
    enrol(world)
    from apps.accounts import views

    monkeypatch.setattr(views.services, "google_login", lambda *a, **k: User.objects.get(email="admin@a.com"))
    r = client().post(A + "google/", {"id_token": "x", "accept_terms": True}, format="json")
    assert r.status_code == 200 and r.json()["data"]["mfa_required"] is True and "access" not in r.json()["data"]


# ---------------------------------------------------- platform switch for the two-step requirement
def test_platform_owner_can_switch_enforcement_off_and_on(world, settings):
    from apps.accounts import mfa
    from tests.conftest import client_for

    settings.MFA_ENFORCEMENT = True
    root = client_for(world["platform"])
    assert mfa.enforced() and mfa.required_for(world["admin_a"])
    bad = root.post("/api/v1/platform/settings/mfa/", {"enforced": False, "password": "wrong"}, format="json")
    assert bad.status_code == 400 and mfa.enforced()
    ok = root.post("/api/v1/platform/settings/mfa/", {"enforced": False, "password": "Str0ng-Passw0rd!x"}, format="json")
    assert ok.status_code == 200 and ok.json()["data"]["enforced"] is False
    assert not mfa.enforced() and not mfa.required_for(world["admin_a"])
    c = client_for(world["admin_a"], "alpha")
    assert c.get("/api/v1/auth/me/").json()["data"]["mfa"]["enforced"] is False
    assert root.post("/api/v1/platform/settings/mfa/", {"enforced": True, "password": "Str0ng-Passw0rd!x"}, format="json").status_code == 200
    assert mfa.enforced() and mfa.required_for(world["admin_a"])
    # a restaurant administrator can never change the platform policy
    assert client_for(world["admin_a"], "alpha").post("/api/v1/platform/settings/mfa/", {"enforced": False, "password": "Str0ng-Passw0rd!x"}, format="json").status_code in (401, 403, 404)
    from apps.core.models import AuditLog
    assert AuditLog.objects.filter(action__in=("platform.mfa_not_enforced", "platform.mfa_enforced")).count() == 2


def test_master_switch_in_configuration_wins(world, settings):
    from apps.accounts import mfa

    settings.MFA_ENFORCEMENT = False
    r = __import__("tests.conftest", fromlist=["client_for"]).client_for(world["platform"]).post("/api/v1/platform/settings/mfa/", {"enforced": True, "password": "Str0ng-Passw0rd!x"}, format="json")
    assert r.status_code == 400 and not mfa.enforced()
