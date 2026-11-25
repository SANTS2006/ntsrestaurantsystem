from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.tenancy import BranchOwnedModel, TenantOwnedModel


class Status(models.TextChoices):
    AWAITING_PAYMENT = "awaiting_payment", "Awaiting Payment"
    PAYMENT_PROCESSING = "payment_processing", "Payment Processing"
    CONFIRMED = "confirmed", "Confirmed"
    RECEIVED = "received", "Received"
    PREPARING = "preparing", "Preparing"
    READY_FOR_PICKUP = "ready_for_pickup", "Ready for Pickup"
    OUT_FOR_DELIVERY = "out_for_delivery", "Out for Delivery"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    REFUND_PENDING = "refund_pending", "Refund Pending"
    REFUNDED = "refunded", "Refunded"


class Fulfilment(models.TextChoices):
    DELIVERY = "delivery"
    PICKUP = "pickup"
    DINE_IN = "dine_in"  # QR / table orders (Phase 9)


class PaymentMethod(models.TextChoices):
    CASH = "cash", "Cash on pickup/delivery"
    MOBILE_MONEY = "mobile_money", "Mobile money"  # online provider arrives in Phase 6


class PaymentStatus(models.TextChoices):
    UNPAID = "unpaid"
    PENDING = "pending"
    PARTIAL = "partial"
    PAID = "paid"
    REFUNDED = "refunded"


class OrderSequence(models.Model):
    """Per-restaurant counter, row-locked to hand out gap-free, unique order numbers."""

    restaurant = models.OneToOneField("tenants.Restaurant", on_delete=models.CASCADE, related_name="+")
    last_number = models.PositiveBigIntegerField(default=0)


class Order(BranchOwnedModel):
    number = models.CharField(max_length=30)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="orders")
    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="cashier_orders")
    source = models.CharField(max_length=10, default="online")  # online | cashier | qr
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AWAITING_PAYMENT, db_index=True)
    fulfilment = models.CharField(max_length=10, choices=Fulfilment.choices)
    payment_method = models.CharField(max_length=15, choices=PaymentMethod.choices)
    payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)

    # Contact + address are snapshots: later profile edits never rewrite history.
    contact_name = models.CharField(max_length=150)
    contact_phone = models.CharField(max_length=30)
    contact_email = models.EmailField(blank=True)
    delivery_address = models.JSONField(default=dict, blank=True)
    customer_notes = models.CharField(max_length=300, blank=True)

    currency = models.CharField(max_length=3)
    tax_rate_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount_reason = models.CharField(max_length=200, blank=True)
    discount_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    delivery_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))  # written by the payment module

    table = models.ForeignKey("qrmenu.DiningTable", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    table_label = models.CharField(max_length=30, blank=True)  # snapshot
    cancellation_requested = models.BooleanField(default=False)
    cancellation_reason = models.CharField(max_length=300, blank=True)
    stock_restored = models.BooleanField(default=False)

    class Meta(BranchOwnedModel.Meta):
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["restaurant", "number"], name="uniq_order_number_per_restaurant"),
            models.CheckConstraint(condition=Q(total__gte=0) & Q(subtotal__gte=0) & Q(amount_paid__gte=0), name="order_amounts_non_negative"),
        ]
        indexes = [models.Index(fields=["restaurant", "branch", "status"]), models.Index(fields=["restaurant", "customer", "-created_at"])]

    def __str__(self):
        return self.number


class OrderItem(TenantOwnedModel):
    """Immutable snapshot of what was bought, at the price it was bought for."""

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="items")
    product = models.ForeignKey("catalog.Product", null=True, on_delete=models.SET_NULL, related_name="+")  # reference only
    product_name = models.CharField(max_length=150)
    variation_name = models.CharField(max_length=80, blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)  # price + variation + addons, per unit
    quantity = models.PositiveSmallIntegerField()
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    addons = models.JSONField(default=list, blank=True)  # [{"name", "price", "quantity"}]
    instructions = models.CharField(max_length=200, blank=True)

    class Meta(TenantOwnedModel.Meta):
        ordering = ["id"]
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="orderitem_quantity_positive")]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("Order items are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Order items cannot be deleted.")


class OrderStatusHistory(TenantOwnedModel):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="history")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    actor_role = models.CharField(max_length=20, blank=True)
    note = models.CharField(max_length=300, blank=True)

    class Meta(TenantOwnedModel.Meta):
        ordering = ["created_at", "id"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("Status history is immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Status history cannot be deleted.")
