from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Append-only security/financial audit trail. Updates and deletes are blocked."""

    restaurant = models.ForeignKey("tenants.Restaurant", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=100, db_index=True)
    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)  # never store secrets/PII beyond need
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["restaurant", "-created_at"])]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("Audit logs are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Audit logs cannot be deleted.")


def audit(action, *, actor=None, restaurant=None, obj=None, metadata=None, request=None):
    ip = None
    if request is not None:
        ip = (request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR")) or None
    return AuditLog.objects.create(
        restaurant=restaurant,
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        object_type=obj.__class__.__name__ if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
        metadata=metadata or {},
        ip_address=ip,
    )


class IdempotencyKey(models.Model):
    """Stores the outcome of a completed sensitive operation so retries never duplicate it."""

    restaurant = models.ForeignKey("tenants.Restaurant", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    operation = models.CharField(max_length=100)
    key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField(null=True)
    response_body = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["restaurant", "user", "operation", "key"], name="uniq_idempotency_scope"),
            models.UniqueConstraint(fields=["user", "operation", "key"], condition=models.Q(restaurant__isnull=True),
                                    name="uniq_idempotency_scope_platform"),
        ]


class DocumentSequence(models.Model):
    """Gap-free per-restaurant counters for business documents (invoices, purchase orders...)."""

    restaurant = models.ForeignKey("tenants.Restaurant", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=20)
    last_number = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["restaurant", "kind"], name="uniq_document_sequence")]


def next_document_number(restaurant, kind, prefix):
    """Call inside a transaction: the row lock serialises concurrent callers so numbers are unique and sequential."""
    seq, _ = DocumentSequence.objects.select_for_update().get_or_create(restaurant=restaurant, kind=kind)
    seq.last_number += 1
    seq.save(update_fields=["last_number"])
    return f"{prefix}-{seq.last_number:06d}"
