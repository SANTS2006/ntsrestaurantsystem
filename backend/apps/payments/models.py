from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.tenancy import BranchOwnedModel, TenantOwnedModel


class Payment(BranchOwnedModel):
    class Status(models.TextChoices):
        PENDING = "pending"
        SUCCEEDED = "succeeded"
        FAILED = "failed"
        MISMATCH = "mismatch"  # provider reported a different amount/currency: needs human investigation

    class Method(models.TextChoices):
        CASH = "cash"
        MOBILE_MONEY = "mobile_money"

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="payments")
    reference = models.CharField(max_length=40)  # our unique transaction reference, sent to the provider
    provider = models.CharField(max_length=20)  # cash | simulated | monime
    method = models.CharField(max_length=15, choices=Method.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    provider_ref = models.CharField(max_length=100, blank=True)
    checkout_url = models.URLField(max_length=500, blank=True)  # the provider's hosted payment page, kept so it can be reopened while pending
    payer_phone = models.CharField(max_length=30, blank=True)
    amount_received = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)  # cash tendered
    change_given = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    shift = models.ForeignKey("cashier.Shift", null=True, blank=True, on_delete=models.PROTECT, related_name="payments")
    failure_reason = models.CharField(max_length=200, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta(BranchOwnedModel.Meta):
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["restaurant", "reference"], name="uniq_payment_reference"),
            models.UniqueConstraint(fields=["provider", "provider_ref"], condition=~Q(provider_ref=""), name="uniq_provider_ref"),
            # at most one in-flight online payment per order: a double click cannot start two charges
            models.UniqueConstraint(fields=["order"], condition=Q(status="pending") & ~Q(provider="cash"), name="one_pending_online_payment_per_order"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive"),
        ]
        indexes = [models.Index(fields=["restaurant", "status", "-created_at"])]


class PaymentEvent(models.Model):
    """Every webhook delivery, stored for audit and replay protection (unique per provider event id)."""

    provider = models.CharField(max_length=20)
    event_id = models.CharField(max_length=120)
    event_type = models.CharField(max_length=60, blank=True)
    provider_ref = models.CharField(max_length=100, blank=True)
    payload = models.JSONField(default=dict)
    payment = models.ForeignKey(Payment, null=True, blank=True, on_delete=models.SET_NULL, related_name="events")
    processed = models.BooleanField(default=False)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["provider", "event_id"], name="uniq_webhook_event")]


class Refund(BranchOwnedModel):
    class Status(models.TextChoices):
        PENDING = "pending"
        SUCCEEDED = "succeeded"
        FAILED = "failed"

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="refunds")
    reference = models.CharField(max_length=40)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=300)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    provider_ref = models.CharField(max_length=100, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    shift = models.ForeignKey("cashier.Shift", null=True, blank=True, on_delete=models.PROTECT, related_name="refunds")  # till the cash came from

    class Meta(BranchOwnedModel.Meta):
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["restaurant", "reference"], name="uniq_refund_reference"),
                       models.CheckConstraint(condition=Q(amount__gt=0), name="refund_amount_positive")]


class ReceiptSequence(models.Model):
    restaurant = models.OneToOneField("tenants.Restaurant", on_delete=models.CASCADE, related_name="+")
    last_number = models.PositiveBigIntegerField(default=0)


class Receipt(BranchOwnedModel):
    """Immutable record of a confirmed payment. `data` is a full snapshot, so later menu, price or profile
    edits can never change a receipt. Corrections are made with refunds/adjustments, never by editing or deleting."""

    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, related_name="receipt")
    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="receipts")
    number = models.CharField(max_length=30)
    data = models.JSONField()

    class Meta(BranchOwnedModel.Meta):
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["restaurant", "number"], name="uniq_receipt_number")]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("Receipts are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Receipts cannot be deleted.")
