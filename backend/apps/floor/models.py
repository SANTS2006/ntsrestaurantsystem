from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.tenancy import BranchOwnedModel


class FloorZone(BranchOwnedModel):
    """An area of a branch (main hall, terrace, bar). Tables belong to a zone for the floor plan."""

    name = models.CharField(max_length=60)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta(BranchOwnedModel.Meta):
        ordering = ["sort_order", "name"]
        constraints = [models.UniqueConstraint(fields=["branch", "name"], name="uniq_zone_name_per_branch")]


class Reservation(BranchOwnedModel):
    class Status(models.TextChoices):
        REQUESTED = "requested"
        CONFIRMED = "confirmed"
        SEATED = "seated"
        COMPLETED = "completed"
        CANCELLED = "cancelled"
        NO_SHOW = "no_show"

    reference = models.CharField(max_length=20)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    customer_name = models.CharField(max_length=150)
    customer_phone = models.CharField(max_length=30)
    customer_email = models.EmailField(blank=True)
    party_size = models.PositiveSmallIntegerField()
    starts_at = models.DateTimeField(db_index=True)
    duration_minutes = models.PositiveSmallIntegerField(default=90)
    table = models.ForeignKey("qrmenu.DiningTable", null=True, blank=True, on_delete=models.PROTECT, related_name="reservations")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CONFIRMED, db_index=True)
    notes = models.CharField(max_length=300, blank=True)
    source = models.CharField(max_length=8, default="public")  # public | staff
    token_hash = models.CharField(max_length=64, blank=True, db_index=True)  # SHA-256 of the guest's private link token; the raw token is only emailed
    cancel_reason = models.CharField(max_length=200, blank=True)
    seated_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    consent_at = models.DateTimeField(null=True, blank=True)

    class Meta(BranchOwnedModel.Meta):
        ordering = ["starts_at", "id"]
        constraints = [models.UniqueConstraint(fields=["restaurant", "reference"], name="uniq_reservation_reference"),
                       models.CheckConstraint(condition=Q(party_size__gte=1) & Q(duration_minutes__gte=15), name="reservation_valid_size")]
        indexes = [models.Index(fields=["restaurant", "branch", "starts_at"])]

    def delete(self, *args, **kwargs):
        raise PermissionError("Reservations are cancelled, not deleted.")
