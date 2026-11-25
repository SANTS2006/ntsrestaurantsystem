from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.tenancy import TenantOwnedModel

METHODS = [("cash", "Cash"), ("bank_transfer", "Bank transfer"), ("mobile_money", "Mobile money"), ("other", "Other")]


class ExpenseCategory(TenantOwnedModel):
    name = models.CharField(max_length=80)
    is_active = models.BooleanField(default=True)

    class Meta(TenantOwnedModel.Meta):
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["restaurant", "name"], name="uniq_expense_category")]


class Expense(TenantOwnedModel):
    """A recorded business cost. Never edited or deleted: a mistake is voided with a reason and re-entered."""

    class Status(models.TextChoices):
        RECORDED = "recorded"
        VOID = "void"

    branch = models.ForeignKey("tenants.Branch", null=True, blank=True, on_delete=models.PROTECT, related_name="+")  # null = restaurant-wide
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name="expenses")
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    expense_date = models.DateField()
    method = models.CharField(max_length=15, choices=METHODS)
    reference = models.CharField(max_length=60, blank=True)
    supplier = models.ForeignKey("procurement.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    purchase_order = models.ForeignKey("procurement.PurchaseOrder", null=True, blank=True, on_delete=models.PROTECT, related_name="expenses")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RECORDED, db_index=True)
    void_reason = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantOwnedModel.Meta):
        ordering = ["-expense_date", "-id"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="expense_amount_positive")]
        indexes = [models.Index(fields=["restaurant", "expense_date"])]

    def delete(self, *args, **kwargs):
        raise PermissionError("Expenses cannot be deleted; void them instead.")


class Invoice(TenantOwnedModel):
    class Status(models.TextChoices):
        DRAFT = "draft"
        ISSUED = "issued"
        PAID = "paid"
        VOID = "void"

    number = models.CharField(max_length=20, blank=True)  # assigned when issued
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    customer_name = models.CharField(max_length=150)
    customer_email = models.EmailField(blank=True)
    customer_address = models.CharField(max_length=300, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=3)
    tax_rate_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    tax_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    notes = models.CharField(max_length=500, blank=True)
    void_reason = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantOwnedModel.Meta):
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["restaurant", "number"], condition=~Q(number=""), name="uniq_invoice_number"),
            models.CheckConstraint(condition=Q(amount_paid__gte=0) & Q(amount_paid__lte=models.F("total")), name="invoice_paid_within_total"),
        ]

    @property
    def balance(self):
        return self.total - self.amount_paid

    def delete(self, *args, **kwargs):
        raise PermissionError("Invoices cannot be deleted; void them instead.")


class InvoiceLine(TenantOwnedModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    description = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=14, decimal_places=2)


class InvoicePayment(TenantOwnedModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    method = models.CharField(max_length=15, choices=METHODS)
    reference = models.CharField(max_length=60, blank=True)
    received_on = models.DateField()
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantOwnedModel.Meta):
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="invoice_payment_positive")]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("Invoice payments are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Invoice payments cannot be deleted.")
