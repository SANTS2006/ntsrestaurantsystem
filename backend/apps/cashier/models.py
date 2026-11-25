from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.tenancy import BranchOwnedModel


class Shift(BranchOwnedModel):
    """A cashier's till session. Closed shifts are immutable financial records."""

    class Status(models.TextChoices):
        OPEN = "open"
        CLOSED = "closed"

    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="shifts")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN, db_index=True)
    opened_at = models.DateTimeField(default=timezone.now)
    opening_cash = models.DecimalField(max_digits=12, decimal_places=2)
    closed_at = models.DateTimeField(null=True, blank=True)
    expected_cash = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)  # frozen at close
    actual_cash = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    variance = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)  # actual - expected
    close_notes = models.CharField(max_length=300, blank=True)

    class Meta(BranchOwnedModel.Meta):
        ordering = ["-opened_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["cashier"], condition=Q(status="open"), name="one_open_shift_per_cashier"),
            models.CheckConstraint(condition=Q(opening_cash__gte=0), name="shift_opening_non_negative"),
        ]
        indexes = [models.Index(fields=["restaurant", "branch", "status"])]

    def save(self, *args, **kwargs):
        if self.pk is not None and Shift.unscoped.filter(pk=self.pk, status=self.Status.CLOSED).exists():
            raise PermissionError("A closed shift cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Shifts cannot be deleted.")


class ShiftAdjustment(BranchOwnedModel):
    """Cash put into / taken out of the till outside of sales. Needs approval by someone other than the requester."""

    class Kind(models.TextChoices):
        CASH_IN = "cash_in", "Cash added to till"
        CASH_OUT = "cash_out", "Cash removed from till"

    class Status(models.TextChoices):
        PENDING = "pending"
        APPROVED = "approved"
        REJECTED = "rejected"

    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name="adjustments")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=300)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)

    class Meta(BranchOwnedModel.Meta):
        ordering = ["-created_at", "-id"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=Decimal("0")), name="adjustment_amount_positive")]

    def delete(self, *args, **kwargs):
        raise PermissionError("Adjustments cannot be deleted.")
