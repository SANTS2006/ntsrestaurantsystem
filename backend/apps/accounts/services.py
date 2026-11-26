"""Authentication business logic. Views stay thin; every flow here is tenant-aware and non-enumerating."""
import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.models import audit
from apps.notifications.services import queue_email
from apps.tenants.models import Branch

from .codes import consume_code, issue_code
from .google import verify_google_id_token
from .models import ConsentRecord, GoogleIdentity, Membership, OneTimeCode, Role, SetupToken, User
from .permissions import accessible_branch_ids, can_assign_role, effective_role


class FlowError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def client_ip(request):
    return (request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR")) or None


def login_url(restaurant):
    base = restaurant.public_url if restaurant else f"{settings.PUBLIC_URL_SCHEME}://{settings.PLATFORM_DOMAIN}"
    return f"{base}/login"


def issue_tokens(user):
    from . import mfa

    refresh = RefreshToken.for_user(user)
    refresh["tv"] = user.token_version
    refresh["mp"] = mfa.required_for(user)  # this account must use a second factor
    refresh["mf"] = bool(user.mfa_enabled)  # ... and has enrolled one (login can only reach here after proving it)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def revoke_tokens(user):
    user.token_version += 1
    user.save(update_fields=["token_version"])


def record_consent(request, user, restaurant, method):
    return ConsentRecord.objects.create(
        user=user, restaurant=restaurant, terms_version=settings.TERMS_VERSION,
        privacy_version=settings.PRIVACY_VERSION, method=method, ip_address=client_ip(request))


def _send_code(user, purpose, template, restaurant):
    code = issue_code(user, purpose, restaurant)
    if code:  # None => resend cooldown active; silently skip (response is identical either way)
        queue_email(template, user.email, {"name": user.full_name, "code": code}, restaurant=restaurant)


# ---- customer registration & email verification ------------------------------------------------
def register_customer(request, *, email, full_name, phone, password):
    tenant = request.tenant
    if tenant is None:
        raise FlowError("no_tenant", "Registration is only available on a restaurant website.", 404)
    email = email.lower()
    with transaction.atomic():
        user = User.objects.select_for_update().filter(email=email).first()
        if user is None:
            user = User.objects.create_user(email, password, full_name=full_name, phone=phone)
            Membership.objects.create(user=user, restaurant=tenant, role=Role.CUSTOMER)
            record_consent(request, user, tenant, ConsentRecord.Method.CHECKBOX)
            _send_code(user, OneTimeCode.Purpose.VERIFY_EMAIL, "verify_email", tenant)
            audit("auth.registered", actor=user, restaurant=tenant, request=request)
        elif not user.email_verified and user.memberships.filter(restaurant=tenant).exists():
            _send_code(user, OneTimeCode.Purpose.VERIFY_EMAIL, "verify_email", tenant)  # password is NOT changed
        else:
            # Existing account: tell the mailbox owner, tell the requester nothing. Max one per day.
            queue_email("account_exists", user.email, {"name": user.full_name, "login_url": login_url(tenant)},
                        restaurant=tenant, dedupe_key=f"account_exists:{user.pk}:{tenant.pk}:{timezone.now():%Y%m%d}")


def resend_verification(request, email):
    user = User.objects.filter(email=email.lower(), email_verified=False, is_active=True).first()
    if user and request.tenant and user.memberships.filter(restaurant=request.tenant).exists():
        _send_code(user, OneTimeCode.Purpose.VERIFY_EMAIL, "verify_email", request.tenant)


def verify_email(request, email, code):
    user = User.objects.filter(email=email.lower(), is_active=True).first()
    tenant = request.tenant
    if not (user and tenant and user.memberships.filter(restaurant=tenant).exists()):
        raise FlowError("invalid_code", "Invalid or expired code.")
    if not consume_code(user, OneTimeCode.Purpose.VERIFY_EMAIL, code):
        raise FlowError("invalid_code", "Invalid or expired code.")
    user.email_verified = True
    user.save(update_fields=["email_verified"])
    audit("auth.email_verified", actor=user, restaurant=tenant, request=request)


# ---- password reset ----------------------------------------------------------------------------
def _eligible_for_host(request, user):
    if request.is_platform:
        return user.is_platform_admin
    return request.tenant is not None and user.memberships.filter(restaurant=request.tenant, is_active=True).exists()


def request_password_reset(request, email):
    user = User.objects.filter(email=email.lower(), is_active=True).first()
    if user and _eligible_for_host(request, user):
        _send_code(user, OneTimeCode.Purpose.PASSWORD_RESET, "password_reset", request.tenant)


def confirm_password_reset(request, email, code, new_password):
    user = User.objects.filter(email=email.lower(), is_active=True).first()
    validate_password(new_password, user)  # raises Django ValidationError -> mapped to 400 by the view
    if not (user and _eligible_for_host(request, user)) or not consume_code(user, OneTimeCode.Purpose.PASSWORD_RESET, code):
        raise FlowError("invalid_code", "Invalid or expired code.")
    set_new_password(request, user, new_password)
    cache.delete(f"login-fail:{user.email}")  # a successful reset lifts the lockout


def set_new_password(request, user, new_password):
    user.set_password(new_password)
    user.email_verified = True  # the code proved mailbox control
    user.must_change_password = False
    user.temp_password_expires_at = None
    user.token_version += 1  # revoke every previously issued token
    user.save(update_fields=["password", "email_verified", "must_change_password", "temp_password_expires_at", "token_version"])
    queue_email("password_changed", user.email, {"name": user.full_name}, restaurant=request.tenant)
    audit("auth.password_changed", actor=user, restaurant=request.tenant, request=request)


# ---- one-time setup links (staff invitations, restaurant admin onboarding) ---------------------
def _hash_token(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_setup_token(user, restaurant):
    SetupToken.objects.filter(user=user, restaurant=restaurant, used_at__isnull=True).update(used_at=timezone.now())
    raw = secrets.token_urlsafe(32)
    SetupToken.objects.create(user=user, restaurant=restaurant, token_hash=_hash_token(raw),
                              expires_at=timezone.now() + timedelta(hours=settings.SETUP_TOKEN_TTL_HOURS))
    return raw


def setup_url(restaurant, raw):
    return f"{login_url(restaurant).rsplit('/login', 1)[0]}/setup-password?token={raw}"


def accept_setup(request, raw_token, password):
    with transaction.atomic():
        token = (SetupToken.objects.select_for_update(of=("self",)).select_related("user")
                 .filter(token_hash=_hash_token(raw_token or "")).first())
        if token is None or token.used_at or token.expires_at < timezone.now() or not token.user.is_active:
            raise FlowError("invalid_token", "This link is invalid or has expired.")
        user = token.user
        validate_password(password, user)
        token.used_at = timezone.now()
        token.save(update_fields=["used_at"])
        set_new_password(request, user, password)


def invite_staff(request, *, email, full_name, phone, role, branch_ids):
    tenant = request.tenant
    actor_role = effective_role(request)
    if tenant is None:
        raise FlowError("no_tenant", "Staff can only be added on a restaurant host.", 404)
    if not can_assign_role(actor_role, role):
        raise FlowError("role_not_allowed", "You cannot assign this role.", 403)
    allowed = accessible_branch_ids(request)
    branches = list(Branch.unscoped.filter(restaurant=tenant, pk__in=branch_ids))
    if len(branches) != len(set(branch_ids)) or any(b.pk not in allowed for b in branches):
        raise FlowError("branch_not_allowed", "One or more branches are not available to you.", 403)
    if role != Role.RESTAURANT_ADMIN and not branches:
        raise FlowError("branch_required", "Select at least one branch for this role.")
    email = email.lower()

    with transaction.atomic():
        user = User.objects.select_for_update().filter(email=email).first()
        if user and user.is_platform_admin:
            raise FlowError("not_allowed", "This email cannot be added.", 400)
        existing = Membership.objects.filter(user=user, restaurant=tenant).first() if user else None
        if existing and existing.role != Role.CUSTOMER:  # customers may be promoted; staff must be changed explicitly
            raise FlowError("already_member", "This person already has staff access to this restaurant.", 409)
        fresh = user is None
        if fresh:
            user = User.objects.create_user(email, None, full_name=full_name, phone=phone)
        elif not user.email_verified:
            user.set_unusable_password()  # unproven mailbox: discard any password someone pre-registered
            user.save(update_fields=["password"])
            revoke_tokens(user)
            fresh = True
        if existing:
            membership, membership.role, membership.is_active = existing, role, True
            membership.save(update_fields=["role", "is_active"])
        else:
            membership = Membership.objects.create(user=user, restaurant=tenant, role=role)
        membership.branches.set(branches if role != Role.RESTAURANT_ADMIN else [])
        label = Role(role).label
        if fresh:
            raw = issue_setup_token(user, tenant)
            queue_email("staff_invitation", email, {
                "name": full_name or user.full_name, "email": email, "role_label": label,
                "setup_url": setup_url(tenant, raw), "login_url": login_url(tenant)}, restaurant=tenant)
        else:
            queue_email("staff_added", email, {"name": user.full_name, "role_label": label,
                                               "login_url": login_url(tenant)}, restaurant=tenant)
        audit("staff.invited", actor=request.user, restaurant=tenant, obj=membership,
              metadata={"role": role, "branches": [b.pk for b in branches]}, request=request)
    return membership


def onboard_restaurant_admin(request, restaurant, email, full_name):
    """Create (or attach) the initial restaurant administrator and send a secure one-time setup link.

    Deliberately NOT a predictable 'initials@year' password: the account has no usable password
    until the owner of the mailbox follows the single-use, expiring link.
    """
    email = email.lower()
    with transaction.atomic():
        user = User.objects.select_for_update().filter(email=email).first()
        if user and user.is_platform_admin:
            raise FlowError("not_allowed", "This email cannot be used as a restaurant administrator.", 400)
        fresh = user is None
        if fresh:
            user = User.objects.create_user(email, None, full_name=full_name)
        elif not user.email_verified:
            user.set_unusable_password()
            user.save(update_fields=["password"])
            revoke_tokens(user)
            fresh = True
        Membership.objects.create(user=user, restaurant=restaurant, role=Role.RESTAURANT_ADMIN)
        if fresh:
            raw = issue_setup_token(user, restaurant)
            queue_email("restaurant_onboarding", email, {
                "name": full_name, "email": email, "restaurant_name": restaurant.name,
                "setup_url": setup_url(restaurant, raw), "login_url": login_url(restaurant)},
                restaurant=restaurant, branded=False)
        else:
            queue_email("staff_added", email, {"name": user.full_name, "role_label": Role.RESTAURANT_ADMIN.label,
                                               "login_url": login_url(restaurant)}, restaurant=restaurant)
    return user


# ---- Google sign-in ----------------------------------------------------------------------------
def google_login(request, token, accept_terms):
    tenant = request.tenant
    if tenant is None:
        raise FlowError("no_tenant", "Google sign-in is only available on a restaurant website.", 404)
    claims = verify_google_id_token(token)  # GoogleAuthError handled by the view
    if not claims["email_verified"]:
        raise FlowError("email_unverified", "Your Google email address is not verified.", 401)

    with transaction.atomic():
        identity = GoogleIdentity.objects.select_related("user").filter(sub=claims["sub"]).first()
        if identity:
            user = identity.user
        else:
            user = User.objects.select_for_update().filter(email=claims["email"]).first()
            if user is None:
                user = User.objects.create_user(claims["email"], None, full_name=claims["name"], email_verified=True)
            elif not user.email_verified:
                # Mailbox control is now proven by Google; discard any password set before verification.
                user.email_verified = True
                user.set_unusable_password()
                user.save(update_fields=["email_verified", "password"])
                revoke_tokens(user)
            GoogleIdentity.objects.create(user=user, sub=claims["sub"])
        if not user.is_active or user.is_platform_admin:
            raise FlowError("not_allowed", "This account cannot use Google sign-in.", 403)
        membership = user.memberships.filter(restaurant=tenant).first()
        if membership is None:
            if not accept_terms:  # raising rolls the whole transaction back: nothing is created
                raise FlowError("terms_required", "Please accept the Terms of Service and Privacy Policy to continue.")
            Membership.objects.create(user=user, restaurant=tenant, role=Role.CUSTOMER)
            record_consent(request, user, tenant, ConsentRecord.Method.GOOGLE_NOTICE)
        elif not membership.is_active:
            raise FlowError("not_allowed", "This account cannot use Google sign-in.", 403)
    audit("auth.google_login", actor=user, restaurant=tenant, request=request)
    return user
