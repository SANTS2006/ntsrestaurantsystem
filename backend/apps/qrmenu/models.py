import secrets
import uuid

from django.conf import settings
from django.db import models

from apps.core.tenancy import BranchOwnedModel


def new_token():
    return secrets.token_urlsafe(24)  # 192 bits: not guessable or enumerable


class DiningTable(BranchOwnedModel):
    label = models.CharField(max_length=30)  # e.g. "Table 4"
    seats = models.PositiveSmallIntegerField(null=True, blank=True)
    zone = models.ForeignKey("floor.FloorZone", null=True, blank=True, on_delete=models.SET_NULL, related_name="tables")
    shape = models.CharField(max_length=6, default="square")  # square | round | rect (floor plan drawing)
    pos_x = models.PositiveSmallIntegerField(default=0)  # floor plan position, 0-100 (% of the zone canvas)
    pos_y = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    qr_token = models.CharField(max_length=64, unique=True, default=new_token)
    qr_regenerated_at = models.DateTimeField(null=True, blank=True)

    class Meta(BranchOwnedModel.Meta):
        ordering = ["branch_id", "label"]
        constraints = [models.UniqueConstraint(fields=["branch", "label"], name="uniq_table_label_per_branch")]


class QRMenuRequest(BranchOwnedModel):
    """A diner's *request*. It is NOT an order and carries no payment until a cashier converts it."""

    class Status(models.TextChoices):
        NEW = "new"
        CONVERTED = "converted"
        REJECTED = "rejected"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)  # lets the diner see the status, nothing else
    table = models.ForeignKey(DiningTable, on_delete=models.PROTECT, related_name="requests")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW, db_index=True)
    items = models.JSONField()  # validated selection (ids, quantities, options); re-priced at conversion
    summary = models.JSONField(default=dict)  # display snapshot: names, options, prices at request time
    customer_name = models.CharField(max_length=100, blank=True)
    customer_phone = models.CharField(max_length=30, blank=True)
    notes = models.CharField(max_length=200, blank=True)
    client_hash = models.CharField(max_length=64, blank=True)  # salted hash of the requester's IP, never the IP itself
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    handled_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.CharField(max_length=200, blank=True)

    class Meta(BranchOwnedModel.Meta):
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["restaurant", "branch", "status", "-created_at"])]
