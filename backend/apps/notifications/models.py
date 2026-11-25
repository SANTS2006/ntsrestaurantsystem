from django.db import models


class EmailLog(models.Model):
    """Delivery record. Never stores the body (bodies can contain one-time codes/links)."""

    class Status(models.TextChoices):
        QUEUED = "queued"
        SENT = "sent"
        RETRYING = "retrying"
        FAILED = "failed"

    restaurant = models.ForeignKey("tenants.Restaurant", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    template = models.CharField(max_length=60)
    to_email = models.EmailField()
    # Unique key makes receipts/notifications idempotent across repeated requests or webhook replays.
    dedupe_key = models.CharField(max_length=200, null=True, blank=True, unique=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    provider_message_id = models.CharField(max_length=100, blank=True)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
