from django.conf import settings
from django.db import models


class BackupRecord(models.Model):
    """Platform-level metadata about one backup archive (never contains the data itself)."""

    class Status(models.TextChoices):
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"

    class Kind(models.TextChoices):
        MANUAL = "manual"
        SCHEDULED = "scheduled"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING, db_index=True)
    storage = models.CharField(max_length=10, blank=True)  # r2 | local
    object_key = models.CharField(max_length=300, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)  # of the stored (encrypted) bytes
    counts = models.JSONField(default=dict, blank=True)  # rows per model, used to verify a restore
    error = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verify_ok = models.BooleanField(null=True, blank=True)
    verify_error = models.CharField(max_length=300, blank=True)
    media_object_key = models.CharField(max_length=300, blank=True)  # separate encrypted archive of uploaded files (logos, photos, avatars)
    media_sha256 = models.CharField(max_length=64, blank=True)
    media_size_bytes = models.PositiveBigIntegerField(default=0)
    media_files = models.PositiveIntegerField(default=0)
    media_note = models.CharField(max_length=200, blank=True)  # why media was skipped, if it was
    pruned_at = models.DateTimeField(null=True, blank=True)  # object removed from storage by retention; the row is kept as history

    class Meta:
        ordering = ["-created_at", "-id"]


class RestoreRecord(models.Model):
    """One restore of the live platform database from a backup. Kept outside the data a restore replaces."""

    class Status(models.TextChoices):
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"

    backup = models.ForeignKey(BackupRecord, on_delete=models.PROTECT, related_name="restores")
    safety_backup = models.ForeignKey(BackupRecord, null=True, blank=True, on_delete=models.PROTECT, related_name="+")  # snapshot of the live data taken just before
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING, db_index=True)
    requested_by = models.CharField(max_length=254)  # email, kept as text because the user rows themselves are replaced
    rows = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=300, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]
