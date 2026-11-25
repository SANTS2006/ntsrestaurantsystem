import re
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from tests.conftest import TenantClient as APIClient

from apps.accounts.google import GoogleAuthError, verify_google_id_token
from apps.accounts.models import (ConsentRecord, GoogleIdentity, Membership, OneTimeCode, Role,
                                  SetupToken, User)
from apps.notifications.models import EmailLog
from apps.notifications.providers import ConsoleProvider, ProviderError
from apps.notifications.services import queue_email
from apps.notifications.tasks import send_email_task

from .conftest import PW, client_for, host

NEW_PW = "Another-Str0ng-Pass9"


@pytest.fixture(autouse=True)
def clean(db):
    ConsoleProvider.outbox.clear()
    cache.clear()
    yield
    cache.clear()


def api(slug="alpha"):
    return APIClient(HTTP_HOST=host(slug))


def code_from(mail):
    return re.search(r'letter-spacing:6px[^>]*>([A-Z2-9]{6})<', mail["html"]).group(1)


def token_from(mail):
    return re.search(r"token=([\w-]+)", mail["html"]).group(1)


def last_mail(to=None):
    mails = [m for m in ConsoleProvider.outbox if to is None or m["to"] == to]
    return mails[-1] if mails else None


def register(slug="alpha", email="new@cust.com", **over):
    body = {"full_name": "New Cust", "email": email, "password": PW, "accept_terms": True, **over}
    return api(slug).post("/api/v1/auth/register/", body, format="json")


def login(slug, email, password):
    return api(slug).post("/api/v1/auth/login/", {"email": email, "password": password}, format="json")


# ---- registration & verification ---------------------------------------------------------------
def test_registration_requires_terms_and_strong_password(world):
    assert register(accept_terms=False).status_code == 400
    assert register(password="short").status_code == 400
    assert not User.objects.filter(email="new@cust.com").exists()


def test_registration_creates_unverified_customer_with_consent_and_hashed_code(world):
    r = register()
    assert r.status_code == 202
    u = User.objects.get(email="new@cust.com")
    assert u.email_verified is False
    assert u.memberships.get().role == Role.CUSTOMER and u.memberships.get().restaurant_id == world["a"].pk
    c = ConsentRecord.objects.get(user=u)
    assert c.method == "checkbox" and c.terms_version and c.restaurant_id == world["a"].pk
    code = code_from(last_mail("new@cust.com"))
    rec = OneTimeCode.objects.get(user=u)
    assert code not in (rec.code_hash, rec.salt) and len(rec.code_hash) == 64
    assert EmailLog.objects.get(to_email="new@cust.com").status == "sent"


def test_unverified_user_cannot_login_until_code_entered(world):
    register()
    assert login("alpha", "new@cust.com", PW).status_code == 403
    code = code_from(last_mail("new@cust.com"))
    assert api().post("/api/v1/auth/verify-email/", {"email": "new@cust.com", "code": code.lower()}, format="json").status_code == 200
    assert login("alpha", "new@cust.com", PW).status_code == 200
    # code is single use
    assert api().post("/api/v1/auth/verify-email/", {"email": "new@cust.com", "code": code}, format="json").status_code == 400


def test_code_locked_after_max_wrong_attempts(world):
    register()
    code = code_from(last_mail("new@cust.com"))
    for _ in range(5):
        assert api().post("/api/v1/auth/verify-email/", {"email": "new@cust.com", "code": "AAAAAA"}, format="json").status_code == 400
    assert api().post("/api/v1/auth/verify-email/", {"email": "new@cust.com", "code": code}, format="json").status_code == 400
    assert User.objects.get(email="new@cust.com").email_verified is False


def test_expired_code_rejected(world):
    register()
    code = code_from(last_mail("new@cust.com"))
    OneTimeCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert api().post("/api/v1/auth/verify-email/", {"email": "new@cust.com", "code": code}, format="json").status_code == 400


def test_resend_cooldown_and_invalidation(world, settings):
    register()
    first = code_from(last_mail("new@cust.com"))
    n = len(ConsoleProvider.outbox)
    api().post("/api/v1/auth/resend-verification/", {"email": "new@cust.com"}, format="json")
    assert len(ConsoleProvider.outbox) == n  # cooldown active: nothing sent
    settings.VERIFICATION_RESEND_COOLDOWN_SECONDS = 0
    r = api().post("/api/v1/auth/resend-verification/", {"email": "new@cust.com"}, format="json")
    assert r.status_code == 202 and len(ConsoleProvider.outbox) == n + 1
    second = code_from(last_mail("new@cust.com"))
    if second != first:  # the old code must no longer work
        assert api().post("/api/v1/auth/verify-email/", {"email": "new@cust.com", "code": first}, format="json").status_code == 400
    assert api().post("/api/v1/auth/verify-email/", {"email": "new@cust.com", "code": second}, format="json").status_code == 200


def test_registration_does_not_reveal_or_hijack_existing_accounts(world):
    fresh = register(email="fresh@cust.com")
    existing = register(email="cust@a.com", password="Attacker-Pass-123!x")
    assert fresh.status_code == existing.status_code == 202 and fresh.data == existing.data
    assert login("alpha", "cust@a.com", PW).status_code == 200  # password unchanged
    assert login("alpha", "cust@a.com", "Attacker-Pass-123!x").status_code == 401
    assert "already have an account" in last_mail("cust@a.com")["html"]


def test_reregistering_unverified_account_keeps_original_password(world):
    register(email="victim@cust.com")
    register(email="victim@cust.com", password="Attacker-Pass-123!x")
    u = User.objects.get(email="victim@cust.com")
    assert u.check_password(PW) and not u.check_password("Attacker-Pass-123!x")


def test_registration_not_available_on_platform_host(world):
    r = APIClient(HTTP_HOST=host()).post("/api/v1/auth/register/", {"full_name": "x", "email": "p@x.com", "password": PW, "accept_terms": True}, format="json")
    assert r.status_code == 404


# ---- password reset & token revocation ---------------------------------------------------------
def test_password_reset_flow_revokes_tokens_and_lifts_lockout(world):
    old = login("alpha", "cust@a.com", PW).data["data"]["access"]
    assert api().post("/api/v1/auth/password-reset/", {"email": "nobody@x.com"}, format="json").status_code == 202
    assert last_mail("nobody@x.com") is None
    r = api().post("/api/v1/auth/password-reset/", {"email": "cust@a.com"}, format="json")
    assert r.status_code == 202
    code = code_from(last_mail("cust@a.com"))
    # weak password does not burn the code
    assert api().post("/api/v1/auth/password-reset/confirm/", {"email": "cust@a.com", "code": code, "new_password": "abc"}, format="json").status_code == 400
    assert api().post("/api/v1/auth/password-reset/confirm/", {"email": "cust@a.com", "code": "ZZZZZZ", "new_password": NEW_PW}, format="json").status_code == 400
    ok = api().post("/api/v1/auth/password-reset/confirm/", {"email": "cust@a.com", "code": code, "new_password": NEW_PW}, format="json")
    assert ok.status_code == 200
    assert login("alpha", "cust@a.com", NEW_PW).status_code == 200
    assert login("alpha", "cust@a.com", PW).status_code == 401
    c = api()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {old}")
    assert c.get("/api/v1/auth/me/").status_code == 401  # pre-reset token revoked
    assert "was just changed" in last_mail("cust@a.com")["html"]


def test_password_reset_only_for_members_of_the_host_tenant(world):
    api("bravo").post("/api/v1/auth/password-reset/", {"email": "cust@a.com"}, format="json")
    assert last_mail("cust@a.com") is None


def test_change_password_revokes_old_tokens_and_returns_new(world):
    c = api()
    old = login("alpha", "cash1@a.com", PW).data["data"]["access"]
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {old}")
    r = c.post("/api/v1/auth/change-password/", {"current_password": PW, "new_password": NEW_PW}, format="json")
    assert r.status_code == 200
    assert c.get("/api/v1/auth/me/").status_code == 401
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['data']['access']}")
    assert c.get("/api/v1/auth/me/").status_code == 200


# ---- staff invitations -------------------------------------------------------------------------
def invite(user, slug="alpha", **over):
    body = {"full_name": "Sam Staff", "email": "sam@staff.com", "role": "cashier", "branch_ids": [], **over}
    return client_for(user, slug).post("/api/v1/staff/invitations/", body, format="json")


def test_manager_invites_cashier_to_own_branch_and_staff_sets_password(world):
    r = invite(world["mgr_a1"], branch_ids=[world["a1"].pk])
    assert r.status_code == 201
    mail = last_mail("sam@staff.com")
    assert "Alpha" in mail["html"] and "sam@staff.com" in mail["html"] and "http://platform.test/alpha" in mail["html"]
    u = User.objects.get(email="sam@staff.com")
    assert not u.has_usable_password()
    assert login("alpha", "sam@staff.com", "anything-1234567").status_code == 401  # no bootstrap password exists
    raw = token_from(mail)
    assert SetupToken.objects.get().token_hash != raw  # only a hash is stored
    assert api().post("/api/v1/auth/setup-password/", {"token": raw, "password": "weak"}, format="json").status_code == 400
    assert api().post("/api/v1/auth/setup-password/", {"token": raw, "password": NEW_PW}, format="json").status_code == 200
    assert login("alpha", "sam@staff.com", NEW_PW).status_code == 200
    assert api().post("/api/v1/auth/setup-password/", {"token": raw, "password": NEW_PW + "x"}, format="json").status_code == 400  # single use


def test_setup_token_expires(world):
    invite(world["mgr_a1"], branch_ids=[world["a1"].pk])
    raw = token_from(last_mail("sam@staff.com"))
    SetupToken.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    assert api().post("/api/v1/auth/setup-password/", {"token": raw, "password": NEW_PW}, format="json").status_code == 400


def test_role_escalation_blocked_on_invitations(world):
    a1 = world["a1"].pk
    assert invite(world["mgr_a1"], role="manager", branch_ids=[a1]).status_code == 403
    assert invite(world["mgr_a1"], role="restaurant_admin").status_code == 403
    assert invite(world["mgr_a1"], role="customer").status_code == 400
    assert invite(world["cashier_a1"], role="cashier", branch_ids=[a1]).status_code == 403
    assert invite(world["cust_a"], role="cashier", branch_ids=[a1]).status_code == 403
    assert invite(world["mgr_a1"], branch_ids=[world["a2"].pk]).status_code == 403  # not their branch
    assert invite(world["mgr_a1"], branch_ids=[world["b1"].pk]).status_code == 403  # other tenant's branch
    assert not User.objects.filter(email="sam@staff.com").exists()


def test_admin_can_invite_manager_but_not_cross_tenant(world):
    assert invite(world["admin_a"], role="manager", branch_ids=[world["a2"].pk]).status_code == 201
    assert invite(world["admin_a"], slug="bravo", email="x@y.com", role="manager", branch_ids=[world["b1"].pk]).status_code == 403


def test_invite_existing_member_conflict_and_platform_admin_protected(world):
    assert invite(world["admin_a"], email="mgr1@a.com", role="cashier", branch_ids=[world["a1"].pk]).status_code == 409
    assert Membership.objects.get(user=world["mgr_a1"], restaurant=world["a"]).role == "manager"  # unchanged
    assert invite(world["admin_a"], email="root@x.com", branch_ids=[world["a1"].pk]).status_code == 400


def test_invite_existing_verified_user_from_other_tenant_gets_no_setup_link(world):
    assert invite(world["admin_a"], email="admin@b.com", role="cashier", branch_ids=[world["a1"].pk]).status_code == 201
    assert "setup-password" not in last_mail("admin@b.com")["html"]
    assert Membership.objects.filter(user=world["admin_b"], restaurant=world["a"], role="cashier").exists()
    assert login("bravo", "admin@b.com", PW).status_code == 200  # existing password intact


def test_invite_discards_password_preregistered_on_unverified_account(world):
    register(slug="alpha", email="sam@staff.com", password="Attacker-Pass-123!x")
    ConsoleProvider.outbox.clear()
    assert invite(world["admin_a"], role="cashier", branch_ids=[world["a1"].pk]).status_code == 201
    assert login("alpha", "sam@staff.com", "Attacker-Pass-123!x").status_code == 401
    assert "setup-password" in last_mail("sam@staff.com")["html"]


# ---- Google ------------------------------------------------------------------------------------
def claims(**over):
    return {"sub": "g-123", "email": "gus@gmail.com", "email_verified": True, "name": "Gus G", **over}


@pytest.fixture
def google(monkeypatch):
    state = {"claims": claims(), "error": False}

    def fake(token):
        if state["error"]:
            raise GoogleAuthError("bad")
        return state["claims"]

    monkeypatch.setattr("apps.accounts.services.verify_google_id_token", fake)
    return state


def g(slug="alpha", **body):
    return api(slug).post("/api/v1/auth/google/", {"id_token": "tok", **body}, format="json")


def test_google_new_user_needs_terms_then_gets_consent_record(world, google):
    r = g()
    assert r.status_code == 400 and r.data["error"]["code"] == "terms_required"
    assert not User.objects.filter(email="gus@gmail.com").exists()  # nothing persisted
    r = g(accept_terms=True)
    assert r.status_code == 200 and "access" in r.data["data"]
    u = User.objects.get(email="gus@gmail.com")
    assert u.email_verified and not u.has_usable_password()
    assert ConsentRecord.objects.get(user=u).method == "google_oauth_notice"
    assert g().status_code == 200  # returning user: no terms needed


def test_google_rejects_invalid_token_unverified_email_and_platform_host(world, google):
    google["error"] = True
    assert g(accept_terms=True).status_code == 401
    google["error"] = False
    google["claims"] = claims(email_verified=False)
    assert g(accept_terms=True).status_code == 401
    google["claims"] = claims()
    assert g(slug=None, accept_terms=True).status_code == 404


def test_google_links_verified_existing_account_by_sub_only(world, google):
    google["claims"] = claims(email="cust@a.com", name="Cust")
    assert g().status_code == 200
    assert GoogleIdentity.objects.get(sub="g-123").user == world["cust_a"]
    assert world["cust_a"].check_password(PW)  # verified account keeps its password
    # same sub, email changed at Google: still maps to the linked account
    google["claims"] = claims(email="changed@gmail.com")
    assert g().status_code == 200 and User.objects.filter(email="changed@gmail.com").count() == 0


def test_google_takeover_via_unverified_preregistration_blocked(world, google):
    register(email="gus@gmail.com", password="Attacker-Pass-123!x")
    assert g(accept_terms=True).status_code == 200  # real mailbox owner signs in with Google
    u = User.objects.get(email="gus@gmail.com")
    assert u.email_verified and not u.check_password("Attacker-Pass-123!x")
    assert login("alpha", "gus@gmail.com", "Attacker-Pass-123!x").status_code == 401


def test_google_platform_admin_cannot_use_google(world, google):
    google["claims"] = claims(email="root@x.com")
    assert g(accept_terms=True).status_code == 403


def test_google_token_verifier_rejects_garbage_without_network(settings):
    with pytest.raises(GoogleAuthError):
        verify_google_id_token("not.a.jwt")


# ---- email infrastructure ----------------------------------------------------------------------
def test_email_dedupe_prevents_duplicate_sends(world):
    assert queue_email("password_changed", "a@b.com", {"name": "A"}, dedupe_key="receipt:1") is not None
    assert queue_email("password_changed", "a@b.com", {"name": "A"}, dedupe_key="receipt:1") is None
    assert len([m for m in ConsoleProvider.outbox if m["to"] == "a@b.com"]) == 1


def test_email_templates_escape_html_and_use_restaurant_branding(world):
    world["a"].primary_color = "#112233"
    queue_email("password_changed", "a@b.com", {"name": "<script>alert(1)</script>"}, restaurant=world["a"])
    m = last_mail("a@b.com")
    assert "<script>" not in m["html"] and "#112233" in m["html"] and m["sender_name"] == "Alpha"


def test_email_retries_then_marks_failed(world, monkeypatch):
    class Boom:
        def send(self, **kw):
            raise ProviderError("down")

    entry = EmailLog.objects.create(template="t", to_email="z@z.com")
    monkeypatch.setattr("apps.notifications.tasks.get_provider", lambda: Boom())
    send_email_task.apply(args=[entry.pk, "s", "h", "n"])
    entry.refresh_from_db()
    assert entry.status == "failed" and entry.attempts >= 2 and "down" in entry.error


def test_verified_customer_can_be_promoted_keeping_password(world):
    assert invite(world["admin_a"], email="cust@a.com", role="cashier", branch_ids=[world["a1"].pk]).status_code == 201
    assert Membership.objects.get(user=world["cust_a"], restaurant=world["a"]).role == "cashier"
    assert login("alpha", "cust@a.com", PW).status_code == 200
