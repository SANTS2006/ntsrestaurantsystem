"""Idempotent execution of sensitive operations (orders, payments, refunds, payroll...).

Usage::

    status, body = run_idempotent(request, "order.create", key, payload, lambda: (201, create_order(...)))

A retry with the same key and payload replays the stored response; the same key with a
different payload is rejected, so a key can never be reused to smuggle in a second operation.
"""
import hashlib
import json

from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from .models import IdempotencyKey


def _hash(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def run_idempotent(request, operation, key, payload, handler):
    if not key or len(key) > 128:
        raise ValidationError({"idempotency_key": "A valid Idempotency-Key header is required."})
    restaurant = getattr(request, "tenant", None)
    user = request.user if request.user.is_authenticated else None
    scope = {"restaurant": restaurant, "user": user, "operation": operation, "key": key}
    digest = _hash(payload)

    with transaction.atomic():
        try:
            with transaction.atomic():
                record = IdempotencyKey.objects.create(request_hash=digest, **scope)
        except IntegrityError:
            record = IdempotencyKey.objects.select_for_update().get(**scope)
            if record.request_hash != digest:
                raise ValidationError({"idempotency_key": "Key was already used with a different request."})
            if record.response_status is None:
                raise ValidationError({"idempotency_key": "A request with this key is still being processed."})
            return record.response_status, record.response_body
        status, body = handler()  # runs inside the same transaction: business effect and key commit together
        record.response_status, record.response_body = status, body
        record.save(update_fields=["response_status", "response_body"])
        return status, body
