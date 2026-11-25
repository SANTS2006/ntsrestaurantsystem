"""Six-character verification codes: CSPRNG, HMAC-hashed at rest, expiring, attempt- and resend-limited."""
import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import OneTimeCode

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I to avoid transcription errors
CODE_LENGTH = 6


def _hash(code: str, salt: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"{salt}:{code.upper()}".encode(), hashlib.sha256).hexdigest()


def issue_code(user, purpose, restaurant=None, payload=""):
    """Return a fresh plaintext code, or None if the resend cooldown is still active.

    Any previously active codes for the same user/purpose are invalidated.
    """
    now = timezone.now()
    with transaction.atomic():
        latest = (OneTimeCode.objects.select_for_update()
                  .filter(user=user, purpose=purpose).order_by("-created_at").first())
        if latest and (now - latest.created_at).total_seconds() < settings.VERIFICATION_RESEND_COOLDOWN_SECONDS:
            return None
        OneTimeCode.objects.filter(user=user, purpose=purpose, consumed_at__isnull=True).update(consumed_at=now)
        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
        salt = secrets.token_hex(8)
        OneTimeCode.objects.create(
            user=user, restaurant=restaurant, purpose=purpose, salt=salt, code_hash=_hash(code, salt), payload=payload,
            expires_at=now + timedelta(seconds=settings.VERIFICATION_CODE_TTL_SECONDS),
        )
    return code


def consume_code(user, purpose, code):
    """Validate and burn a code; returns the record (truthy) or None. Wrong guesses count; the code dies after too many attempts."""
    code = (code or "").strip().upper()
    now = timezone.now()
    with transaction.atomic():
        record = (OneTimeCode.objects.select_for_update()
                  .filter(user=user, purpose=purpose, consumed_at__isnull=True).order_by("-created_at").first())
        if record is None or record.expires_at < now:
            return None
        if record.attempts >= settings.VERIFICATION_CODE_MAX_ATTEMPTS:
            record.consumed_at = now
            record.save(update_fields=["consumed_at"])
            return None
        if len(code) == CODE_LENGTH and hmac.compare_digest(_hash(code, record.salt), record.code_hash):
            record.consumed_at = now  # single use
            record.save(update_fields=["consumed_at"])
            return record
        record.attempts += 1
        if record.attempts >= settings.VERIFICATION_CODE_MAX_ATTEMPTS:
            record.consumed_at = now
        record.save(update_fields=["attempts", "consumed_at"])
        return None
