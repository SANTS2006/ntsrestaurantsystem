from django.conf import settings
from django.db import models

from apps.core.tenancy import TenantOwnedModel


class CustomerAddress(TenantOwnedModel):
    """A customer's saved delivery address, private to one restaurant relationship."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="addresses")
    label = models.CharField(max_length=40, default="Home")
    recipient_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    line1 = models.CharField(max_length=200)
    line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100)
    delivery_notes = models.CharField(max_length=250, blank=True)
    is_default = models.BooleanField(default=False)

    class Meta(TenantOwnedModel.Meta):
        ordering = ["-is_default", "-updated_at"]
        indexes = [models.Index(fields=["restaurant", "user"])]


class CustomerNote(TenantOwnedModel):
    """Staff-only note about a customer (allergies, preferences). Append-only."""

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="staff_notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    text = models.CharField(max_length=500)

    class Meta(TenantOwnedModel.Meta):
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("Customer notes are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Customer notes cannot be deleted.")
