from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.tenancy import TenantOwnedModel


class Status(models.TextChoices):
    NEW = "new", "New"
    UNDER_REVIEW = "under_review", "Under Review"
    QUOTATION_SENT = "quotation_sent", "Quotation Sent"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    IN_PROGRESS = "in_progress", "In Progress"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class EventType(models.TextChoices):
    WEDDING = "wedding", "Wedding"
    CORPORATE = "corporate", "Corporate event"
    BIRTHDAY = "birthday", "Birthday"
    PRIVATE_DINING = "private_dining", "Private dining"
    OUTDOOR = "outdoor", "Outdoor catering"
    OTHER = "other", "Other event"


class CateringSequence(models.Model):
    restaurant = models.OneToOneField("tenants.Restaurant", on_delete=models.CASCADE, related_name="+")
    last_number = models.PositiveBigIntegerField(default=0)


class CateringRequest(TenantOwnedModel):
    reference = models.CharField(max_length=20)
    branch = models.ForeignKey("tenants.Branch", null=True, blank=True, on_delete=models.PROTECT, related_name="+")  # null = not yet allocated (admin triage)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.NEW, db_index=True)

    customer_name = models.CharField(max_length=150)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=30)
    event_type = models.CharField(max_length=15, choices=EventType.choices)
    event_date = models.DateField()
    event_location = models.CharField(max_length=250)
    guests = models.PositiveIntegerField()
    services = models.ManyToManyField("catalog.Service", blank=True, related_name="+")
    food_preferences = models.TextField(blank=True)
    budget = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3)
    requirements = models.TextField(blank=True)
    consent_at = models.DateTimeField()  # the customer agreed to the privacy policy when submitting
    client_hash = models.CharField(max_length=64, blank=True)
    cancel_reason = models.CharField(max_length=300, blank=True)

    class Meta(TenantOwnedModel.Meta):
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["restaurant", "reference"], name="uniq_catering_reference"),
                       models.CheckConstraint(condition=Q(guests__gt=0), name="catering_guests_positive")]
        indexes = [models.Index(fields=["restaurant", "status", "-created_at"])]


class CateringStatusHistory(TenantOwnedModel):
    request = models.ForeignKey(CateringRequest, on_delete=models.PROTECT, related_name="history")
    from_status = models.CharField(max_length=15, blank=True)
    to_status = models.CharField(max_length=15)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    note = models.CharField(max_length=300, blank=True)

    class Meta(TenantOwnedModel.Meta):
        ordering = ["created_at", "id"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("History is immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("History cannot be deleted.")


class CateringNote(TenantOwnedModel):
    """Staff-only record. `kind=email` entries log messages sent to the customer. Never shown publicly."""

    request = models.ForeignKey(CateringRequest, on_delete=models.PROTECT, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=10, default="note")  # note | email
    text = models.TextField(max_length=3000)

    class Meta(TenantOwnedModel.Meta):
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("Notes are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Notes cannot be deleted.")


class Quotation(TenantOwnedModel):
    class QStatus(models.TextChoices):
        DRAFT = "draft"
        SENT = "sent"
        ACCEPTED = "accepted"
        DECLINED = "declined"
        SUPERSEDED = "superseded"

    request = models.ForeignKey(CateringRequest, on_delete=models.PROTECT, related_name="quotations")
    version = models.PositiveSmallIntegerField()
    items = models.JSONField()  # [{description, quantity, unit_price, line_total}] (line totals computed by the server)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_rate_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    valid_until = models.DateField()
    terms = models.TextField(blank=True, max_length=3000)
    status = models.CharField(max_length=10, choices=QStatus.choices, default=QStatus.DRAFT)
    token_hash = models.CharField(max_length=64, unique=True, null=True, blank=True)  # sha256 of the emailed link token
    sent_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    accepted_via = models.CharField(max_length=20, blank=True)  # customer_link | recorded_by_staff
    response_note = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantOwnedModel.Meta):
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["request", "version"], name="uniq_quotation_version"),
                       models.CheckConstraint(condition=Q(total__gte=0), name="quotation_total_non_negative")]


class CateringPayment(TenantOwnedModel):
    """Money received for (or returned from) a catering booking. Recorded by staff; never edited or deleted."""

    class Kind(models.TextChoices):
        DEPOSIT = "deposit"
        PAYMENT = "payment"
        REFUND = "refund"

    request = models.ForeignKey(CateringRequest, on_delete=models.PROTECT, related_name="payments")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=15)  # cash | mobile_money | bank_transfer | other
    reference = models.CharField(max_length=60, blank=True)
    received_on = models.DateField()
    note = models.CharField(max_length=200, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantOwnedModel.Meta):
        ordering = ["received_on", "id"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="catering_payment_positive")]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("Payments are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Payments cannot be deleted.")
