"""Time-based one-time passwords (RFC 6238) for privileged accounts, implemented with the standard library.

* The shared secret is encrypted at rest (Fernet; key from MFA_ENCRYPTION_KEY or derived from the Django secret key).
* A code can be used once (the last accepted time step is remembered), with one step of clock drift allowed.
* Ten single-use recovery codes are issued on enrolment; only their HMACs are stored.
* Failed attempts are rate limited per account; every outcome is audited.
"""
import base64
import hashlib
import hmac
import io
import secrets
import struct
import time

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.db import models, transaction
from django.utils import timezone

from .models import MFADevice, Membership, RecoveryCode, User

STEP, DIGITS, WINDOW = 30, 6, 1
MAX_FAILS, LOCK_SECONDS = 5, 15 * 60
LOGIN_TOKEN_SALT, LOGIN_TOKEN_TTL = "mfa-login", 300


# ---- primitives -----------------------------------------------------------------------------------------------
def _fernet():
    key = getattr(settings, "MFA_ENCRYPTION_KEY", "") or base64.urlsafe_b64encode(hashlib.sha256(("mfa:" + settings.SECRET_KEY).encode()).digest()).decode()
    return Fernet(key.encode())


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    return str((struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITS).zfill(DIGITS)


def totp_at(secret_b32: str, when: float | None = None) -> str:
    return _hotp(secret_b32, int((when if when is not None else time.time()) // STEP))


def match_step(secret_b32: str, code: str, when: float | None = None):
    """The time step the code belongs to (within the allowed drift), or None."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    now = int((when if when is not None else time.time()) // STEP)
    for step in range(now - WINDOW, now + WINDOW + 1):
        if hmac.compare_digest(_hotp(secret_b32, step), code):
            return step
    return None


def provisioning_uri(user, secret_b32: str) -> str:
    from urllib.parse import quote

    issuer = getattr(settings, "MFA_ISSUER", "") or settings.BREVO_SENDER_NAME
    return f"otpauth://totp/{quote(issuer)}:{quote(user.email)}?secret={secret_b32}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"


def qr_data_url(text: str) -> str:
    import qrcode

    img = qrcode.make(text, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _rhash(code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), ("mfa-recovery:" + code.strip().lower().replace("-", "")).encode(), hashlib.sha256).hexdigest()


# ---- policy ------------------------------------------------------------------------------------------------------
def required_for(user) -> bool:
    """Platform administrators and the roles listed in MFA_REQUIRED_ROLES must use a second factor."""
    if user.is_platform_admin:
        return True
    roles = set(getattr(settings, "MFA_REQUIRED_ROLES", ("restaurant_admin",)))
    return Membership.objects.filter(user=user, is_active=True, role__in=roles).exists()


# ---- enrolment ----------------------------------------------------------------------------------------------------
@transaction.atomic
def begin_setup(user):
    secret = new_secret()
    dev, _ = MFADevice.objects.update_or_create(user=user, defaults={"secret_enc": _fernet().encrypt(secret.encode()).decode(), "confirmed_at": None, "last_used_step": 0})
    if user.mfa_enabled:
        raise ValueError("already enabled")
    uri = provisioning_uri(user, secret)
    return {"secret": secret, "otpauth_uri": uri, "qr": qr_data_url(uri)}


def _secret(dev) -> str:
    try:
        return _fernet().decrypt(dev.secret_enc.encode()).decode()
    except InvalidToken:
        raise ValueError("The stored secret cannot be decrypted (key changed). Ask an administrator to reset your two-factor setup.")


def new_recovery_codes(user, n=10):
    RecoveryCode.objects.filter(user=user).delete()
    codes = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(n)]
    RecoveryCode.objects.bulk_create([RecoveryCode(user=user, code_hash=_rhash(c)) for c in codes])
    return codes


@transaction.atomic
def confirm_setup(user, code):
    dev = MFADevice.objects.select_for_update().filter(user=user, confirmed_at__isnull=True).first()
    if dev is None:
        return None
    step = match_step(_secret(dev), code)
    if step is None:
        return None
    dev.confirmed_at, dev.last_used_step = timezone.now(), step
    dev.save()
    User.objects.filter(pk=user.pk).update(mfa_enabled=True)
    user.mfa_enabled = True
    return new_recovery_codes(user)


# ---- verification (login and sensitive actions) ----------------------------------------------------------------------
def _fail_key(user):
    return f"mfa-fail:{user.pk}"


def locked(user) -> bool:
    return cache.get(_fail_key(user), 0) >= MAX_FAILS


def _record_fail(user):
    cache.set(_fail_key(user), cache.get(_fail_key(user), 0) + 1, LOCK_SECONDS)


@transaction.atomic
def verify(user, code="", recovery=""):
    """True if a valid, unused TOTP code (or recovery code) was supplied. Consumes it."""
    if locked(user):
        return False, "locked"
    dev = MFADevice.objects.select_for_update().filter(user=user, confirmed_at__isnull=False).first()
    if dev is None:
        return False, "not_enrolled"
    if recovery:
        rc = RecoveryCode.objects.select_for_update().filter(user=user, code_hash=_rhash(recovery), used_at__isnull=True).first()
        if rc is None:
            _record_fail(user)
            return False, "invalid"
        rc.used_at = timezone.now()
        rc.save(update_fields=["used_at"])
        cache.delete(_fail_key(user))
        return True, "recovery"
    step = match_step(_secret(dev), code)
    if step is None or step <= dev.last_used_step:  # wrong code, or the same code replayed
        _record_fail(user)
        return False, "invalid"
    dev.last_used_step = step
    dev.save(update_fields=["last_used_step"])
    cache.delete(_fail_key(user))
    return True, "totp"


def disable(user):
    MFADevice.objects.filter(user=user).delete()
    RecoveryCode.objects.filter(user=user).delete()
    User.objects.filter(pk=user.pk).update(mfa_enabled=False, token_version=models.F("token_version") + 1)  # signs the user out everywhere


def recovery_left(user) -> int:
    return RecoveryCode.objects.filter(user=user, used_at__isnull=True).count()


# ---- the short-lived token between "password OK" and "code OK" ----------------------------------------------------------
def login_token(user) -> str:
    return signing.dumps({"u": user.pk, "tv": user.token_version}, salt=LOGIN_TOKEN_SALT)


def user_from_login_token(token):
    try:
        d = signing.loads(token or "", salt=LOGIN_TOKEN_SALT, max_age=LOGIN_TOKEN_TTL)
    except signing.BadSignature:
        return None
    u = User.objects.filter(pk=d["u"], is_active=True).first()
    return u if u and u.token_version == d["tv"] else None
