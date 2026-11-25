from django.db import transaction
from rest_framework import serializers

from apps.core.uploads import image_field

from .models import (Category, GalleryImage, Product, ProductAddon, ProductImage, ProductVariation, Service,
                     StockMovement, unique_slug)

PRODUCT_IMAGE_MAX = 3 * 1024 * 1024
TRACKED_PRODUCT_FIELDS = ["name", "base_price", "offer_price", "offer_label", "offer_ends_at", "is_available",
                          "is_featured", "is_archived", "category_id", "track_inventory", "prep_time_minutes"]


class ImageUploadSerializer(serializers.Serializer):
    image = image_field(PRODUCT_IMAGE_MAX)


class TenantScopedMixin:
    @property
    def tenant(self):
        return self.context["request"].tenant


class CategorySerializer(TenantScopedMixin, serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug", "description", "sort_order", "is_active"]
        read_only_fields = ["id", "slug"]

    def create(self, validated):
        validated["slug"] = unique_slug(Category, validated["restaurant"], validated["name"])
        return super().create(validated)


class VariationSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = ProductVariation
        fields = ["id", "kind", "name", "price_delta", "is_default", "is_available"]

    def validate_price_delta(self, v):
        if v < 0:
            raise serializers.ValidationError("Price difference cannot be negative.")
        return v


class AddonSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = ProductAddon
        fields = ["id", "name", "price", "max_quantity", "is_available"]

    def validate_price(self, v):
        if v < 0:
            raise serializers.ValidationError("Price cannot be negative.")
        return v


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "image", "alt_text", "sort_order"]


def _sync(product, items, model):
    """Make the product's children equal `items` (update by id, create new, delete missing)."""
    existing = {c.pk: c for c in model.unscoped.filter(product=product)}
    keep = set()
    for order, raw in enumerate(items):
        item = dict(raw)
        pk = item.pop("id", None)
        if pk is not None:
            obj = existing.get(pk)
            if obj is None:
                raise serializers.ValidationError({"detail": "Unknown child id."})
            for k, v in item.items():
                setattr(obj, k, v)
            obj.sort_order = order
            obj.save()
        else:
            obj = model(product=product, restaurant=product.restaurant, sort_order=order, **item)
            obj.save()
        keep.add(obj.pk)
    for stale in model.unscoped.filter(product=product).exclude(pk__in=keep):
        stale.delete()  # per-instance so cache-invalidating signals fire


class ProductManageSerializer(TenantScopedMixin, serializers.ModelSerializer):
    category = serializers.PrimaryKeyRelatedField(queryset=Category.unscoped.all())
    variations = VariationSerializer(many=True, required=False)
    addons = AddonSerializer(many=True, required=False)
    image = serializers.SerializerMethodField()
    effective_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    sold_out = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = ["id", "category", "name", "slug", "description", "image", "base_price", "offer_price", "offer_label",
                  "offer_ends_at", "effective_price", "is_available", "is_featured", "is_popular", "is_archived",
                  "prep_time_minutes", "ingredients", "allow_instructions", "track_inventory", "stock_quantity",
                  "low_stock_threshold", "sold_out", "sort_order", "variations", "addons"]
        # Stock changes only through the audited stock endpoint; archiving only through archive/restore.
        read_only_fields = ["id", "slug", "stock_quantity", "is_archived"]

    def get_image(self, obj):
        request = self.context.get("request")
        return request.build_absolute_uri(obj.image.url) if obj.image else None

    def validate_category(self, value):
        if value.restaurant_id != self.tenant.pk:  # IDOR: category ids from other tenants are rejected
            raise serializers.ValidationError("Invalid category.")
        return value

    def validate_ingredients(self, value):
        if not isinstance(value, list) or not all(isinstance(i, str) and len(i) <= 80 for i in value) or len(value) > 50:
            raise serializers.ValidationError("Ingredients must be a list of short strings.")
        return value

    def validate(self, attrs):
        base = attrs.get("base_price", getattr(self.instance, "base_price", None))
        offer = attrs.get("offer_price", getattr(self.instance, "offer_price", None))
        if base is not None and base < 0:
            raise serializers.ValidationError({"base_price": "Price cannot be negative."})
        if offer is not None and base is not None and not (0 <= offer < base):
            raise serializers.ValidationError({"offer_price": "Offer price must be lower than the regular price."})
        variations = attrs.get("variations") or []
        if len({v["name"].strip().lower() for v in variations}) != len(variations):
            raise serializers.ValidationError({"variations": "Variation names must be unique."})
        if sum(1 for v in variations if v.get("is_default")) > 1:
            raise serializers.ValidationError({"variations": "Only one variation can be the default."})
        addons = attrs.get("addons") or []
        if len({a["name"].strip().lower() for a in addons}) != len(addons):
            raise serializers.ValidationError({"addons": "Add-on names must be unique."})
        return attrs

    @transaction.atomic
    def create(self, validated):
        variations, addons = validated.pop("variations", []), validated.pop("addons", [])
        validated["slug"] = unique_slug(Product, validated["restaurant"], validated["name"])
        product = super().create(validated)
        _sync(product, variations, ProductVariation)
        _sync(product, addons, ProductAddon)
        return product

    @transaction.atomic
    def update(self, instance, validated):
        variations, addons = validated.pop("variations", None), validated.pop("addons", None)
        product = super().update(instance, validated)
        if variations is not None:
            _sync(product, variations, ProductVariation)
        if addons is not None:
            _sync(product, addons, ProductAddon)
        return product


class StockAdjustSerializer(serializers.Serializer):
    delta = serializers.IntegerField()
    reason = serializers.ChoiceField(choices=[StockMovement.Reason.RESTOCK, StockMovement.Reason.ADJUSTMENT,
                                              StockMovement.Reason.WASTE, StockMovement.Reason.RETURN])
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")

    def validate_delta(self, v):
        if v == 0 or abs(v) > 100000:
            raise serializers.ValidationError("Enter a non-zero quantity change.")
        return v


class StockMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    actor_email = serializers.CharField(source="actor.email", read_only=True, default=None)

    class Meta:
        model = StockMovement
        fields = ["id", "product", "product_name", "delta", "quantity_after", "reason", "note", "actor_email", "created_at"]


class ServiceSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = Service
        fields = ["id", "name", "slug", "description", "image", "is_active", "sort_order"]
        read_only_fields = ["id", "slug"]

    def get_image(self, obj):
        request = self.context.get("request")
        return request.build_absolute_uri(obj.image.url) if obj.image else None

    def create(self, validated):
        validated["slug"] = unique_slug(Service, validated["restaurant"], validated["name"])
        return super().create(validated)


class GallerySerializer(serializers.ModelSerializer):
    image = image_field(PRODUCT_IMAGE_MAX)

    class Meta:
        model = GalleryImage
        fields = ["id", "image", "caption", "sort_order"]
        read_only_fields = ["id"]

    def to_representation(self, obj):
        data = super().to_representation(obj)
        request = self.context.get("request")
        data["image"] = request.build_absolute_uri(obj.image.url) if request else obj.image.url
        return data


# ---- public (customer-facing) shapes: no stock numbers, no internal fields -------------------------
def _abs(request, f):
    return request.build_absolute_uri(f.url) if f else None


def public_product(p, request):
    return {
        "id": p.pk, "slug": p.slug, "name": p.name, "description": p.description, "image": _abs(request, p.image),
        "price": str(p.effective_price), "regular_price": str(p.base_price),
        "offer_label": p.offer_label if p.offer_active else "", "on_offer": p.offer_active,
        "is_featured": p.is_featured, "is_popular": p.is_popular, "prep_time_minutes": p.prep_time_minutes,
        "ingredients": p.ingredients, "allow_instructions": p.allow_instructions, "sold_out": p.sold_out,
        "category_slug": p.category.slug, "category_name": p.category.name,
        "variations": [{"id": v.pk, "kind": v.kind, "name": v.name, "price_delta": str(v.price_delta), "is_default": v.is_default}
                       for v in p.variations.all() if v.is_available],
        "addons": [{"id": a.pk, "name": a.name, "price": str(a.price), "max_quantity": a.max_quantity}
                   for a in p.addons.all() if a.is_available],
    }
