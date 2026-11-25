from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from django.utils.text import slugify

from apps.core.tenancy import TenantOwnedModel
from apps.core.uploads import random_upload_path


def unique_slug(model, restaurant, text, exclude_pk=None, max_len=60):
    base = slugify(text)[:max_len] or "item"
    slug, n = base, 2
    qs = model.unscoped.filter(restaurant=restaurant)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    while qs.filter(slug=slug).exists():
        slug, n = f"{base[: max_len - 4]}-{n}", n + 1
    return slug


class Category(TenantOwnedModel):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=64)
    description = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta(TenantOwnedModel.Meta):
        ordering = ["sort_order", "name"]
        verbose_name_plural = "categories"
        constraints = [models.UniqueConstraint(fields=["restaurant", "slug"], name="uniq_category_slug_per_restaurant")]


class Product(TenantOwnedModel):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=64)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to=random_upload_path("products"), blank=True)
    base_price = models.DecimalField(max_digits=12, decimal_places=2)
    offer_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    offer_label = models.CharField(max_length=60, blank=True)
    offer_ends_at = models.DateTimeField(null=True, blank=True)
    is_available = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    is_popular = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)  # soft delete: history (orders) must keep resolving
    prep_time_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    ingredients = models.JSONField(default=list, blank=True)
    allow_instructions = models.BooleanField(default=True)
    track_inventory = models.BooleanField(default=False)
    stock_quantity = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=5)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta(TenantOwnedModel.Meta):
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["restaurant", "slug"], name="uniq_product_slug_per_restaurant"),
            models.CheckConstraint(condition=Q(base_price__gte=0), name="product_price_non_negative"),
            models.CheckConstraint(condition=Q(offer_price__isnull=True) | (Q(offer_price__gte=0) & Q(offer_price__lt=F("base_price"))),
                                   name="product_offer_below_base"),
        ]
        indexes = [models.Index(fields=["restaurant", "is_archived", "is_available"]),
                   models.Index(fields=["restaurant", "category"])]

    @property
    def offer_active(self):
        return self.offer_price is not None and (self.offer_ends_at is None or self.offer_ends_at > timezone.now())

    @property
    def effective_price(self) -> Decimal:
        return self.offer_price if self.offer_active else self.base_price

    @property
    def sold_out(self):
        return self.track_inventory and self.stock_quantity <= 0


class ProductImage(TenantOwnedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to=random_upload_path("products/gallery"))
    alt_text = models.CharField(max_length=150, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta(TenantOwnedModel.Meta):
        ordering = ["sort_order", "id"]


class ProductVariation(TenantOwnedModel):
    class Kind(models.TextChoices):
        SIZE = "size"
        VARIATION = "variation"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variations")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.SIZE)
    name = models.CharField(max_length=80)
    price_delta = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    is_default = models.BooleanField(default=False)
    is_available = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta(TenantOwnedModel.Meta):
        ordering = ["sort_order", "id"]
        constraints = [models.UniqueConstraint(fields=["product", "name"], name="uniq_variation_name_per_product"),
                       models.CheckConstraint(condition=Q(price_delta__gte=0), name="variation_delta_non_negative")]


class ProductAddon(TenantOwnedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="addons")
    name = models.CharField(max_length=80)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    max_quantity = models.PositiveSmallIntegerField(default=1)
    is_available = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta(TenantOwnedModel.Meta):
        ordering = ["sort_order", "id"]
        constraints = [models.UniqueConstraint(fields=["product", "name"], name="uniq_addon_name_per_product"),
                       models.CheckConstraint(condition=Q(price__gte=0), name="addon_price_non_negative")]


class StockMovement(TenantOwnedModel):
    """Append-only inventory ledger."""

    class Reason(models.TextChoices):
        RESTOCK = "restock"
        ADJUSTMENT = "adjustment"
        WASTE = "waste"
        SALE = "sale"  # written by the order flow (Phase 5)
        RETURN = "return"

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="stock_movements")
    delta = models.IntegerField()
    quantity_after = models.PositiveIntegerField()
    reason = models.CharField(max_length=12, choices=Reason.choices)
    note = models.CharField(max_length=200, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantOwnedModel.Meta):
        ordering = ["-created_at", "-id"]
        constraints = [models.CheckConstraint(condition=~Q(delta=0), name="stock_delta_non_zero")]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("Stock movements are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Stock movements cannot be deleted.")


class Service(TenantOwnedModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=64)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to=random_upload_path("services"), blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta(TenantOwnedModel.Meta):
        ordering = ["sort_order", "name"]
        constraints = [models.UniqueConstraint(fields=["restaurant", "slug"], name="uniq_service_slug_per_restaurant")]


class GalleryImage(TenantOwnedModel):
    image = models.ImageField(upload_to=random_upload_path("gallery"))
    caption = models.CharField(max_length=150, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta(TenantOwnedModel.Meta):
        ordering = ["sort_order", "-id"]
