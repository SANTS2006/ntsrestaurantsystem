from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.tenancy import BranchOwnedModel, TenantOwnedModel

UNITS = [("kg", "kg"), ("g", "g"), ("l", "litre"), ("ml", "ml"), ("pcs", "pieces"), ("pack", "packs"), ("box", "boxes")]


class Supplier(TenantOwnedModel):
    name = models.CharField(max_length=150)
    contact_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=250, blank=True)
    notes = models.CharField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)  # suppliers are archived, never deleted (purchase history)

    class Meta(TenantOwnedModel.Meta):
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["restaurant", "name"], name="uniq_supplier_name")]

    def __str__(self):
        return self.name


class Ingredient(TenantOwnedModel):
    name = models.CharField(max_length=150)
    unit = models.CharField(max_length=5, choices=UNITS, default="kg")
    low_stock_threshold = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))
    last_unit_cost = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("0"))  # updated when stock is received
    is_active = models.BooleanField(default=True)

    class Meta(TenantOwnedModel.Meta):
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["restaurant", "name"], name="uniq_ingredient_name")]


class IngredientStock(BranchOwnedModel):
    """Stock on hand of one ingredient at one branch. May go negative (sales are never blocked) and is flagged as low."""

    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT, related_name="stocks")
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))

    class Meta(BranchOwnedModel.Meta):
        constraints = [models.UniqueConstraint(fields=["ingredient", "branch"], name="uniq_ingredient_branch_stock")]


class IngredientMovement(BranchOwnedModel):
    """Append-only ledger of every change to ingredient stock."""

    class Reason(models.TextChoices):
        PURCHASE = "purchase"
        SALE = "sale"
        SALE_RETURN = "sale_return"
        WASTE = "waste"
        ADJUSTMENT = "adjustment"
        OPENING = "opening"

    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT, related_name="movements")
    delta = models.DecimalField(max_digits=14, decimal_places=3)
    quantity_after = models.DecimalField(max_digits=14, decimal_places=3)
    reason = models.CharField(max_length=12, choices=Reason.choices)
    note = models.CharField(max_length=200, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    purchase_order = models.ForeignKey("PurchaseOrder", null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta(BranchOwnedModel.Meta):
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("Stock movements are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Stock movements cannot be deleted.")


class RecipeLine(TenantOwnedModel):
    """Quantity of an ingredient used by ONE unit of a product sold."""

    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="recipe_lines")
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT, related_name="recipe_lines")
    quantity = models.DecimalField(max_digits=12, decimal_places=4)

    class Meta(TenantOwnedModel.Meta):
        constraints = [models.UniqueConstraint(fields=["product", "ingredient"], name="uniq_recipe_line"),
                       models.CheckConstraint(condition=Q(quantity__gt=0), name="recipe_qty_positive")]


class PurchaseOrder(BranchOwnedModel):
    class Status(models.TextChoices):
        DRAFT = "draft"
        ORDERED = "ordered"
        PARTIAL = "partially_received"
        RECEIVED = "received"
        CANCELLED = "cancelled"

    number = models.CharField(max_length=20)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    expected_date = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=500, blank=True)
    currency = models.CharField(max_length=3)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    ordered_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=300, blank=True)

    class Meta(BranchOwnedModel.Meta):
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["restaurant", "number"], name="uniq_po_number")]


class PurchaseOrderLine(TenantOwnedModel):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4)
    received = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))

    class Meta(TenantOwnedModel.Meta):
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0) & Q(unit_cost__gte=0) & Q(received__gte=0), name="po_line_valid")]
