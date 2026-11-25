from django.db import transaction
from django.db.models import F
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.permissions import IsManagerOrAbove
from apps.core.models import audit

from .models import Category, GalleryImage, Product, Service, StockMovement
from .serializers import (TRACKED_PRODUCT_FIELDS, CategorySerializer, GallerySerializer, ImageUploadSerializer,
                          ProductManageSerializer, ServiceSerializer, StockAdjustSerializer, StockMovementSerializer)


class TenantViewSet(viewsets.ModelViewSet):
    """Base for tenant-owned resources managed by administrators and managers.

    Queryset is always filtered by the host-resolved tenant (never a client value); records are archived/deactivated, not deleted.
    """

    permission_classes = [IsManagerOrAbove]
    model = None
    # DELETE is routed (the image action needs it) but generic record deletion is refused: archive/deactivate instead.
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE")

    def get_queryset(self):
        return self.model.unscoped.filter(restaurant=self.request.tenant)

    def perform_create(self, serializer):
        obj = serializer.save(restaurant=self.request.tenant)
        audit(f"{self.model.__name__.lower()}.created", actor=self.request.user, restaurant=self.request.tenant, obj=obj,
              request=self.request)

    def perform_update(self, serializer):
        obj = serializer.save()
        audit(f"{self.model.__name__.lower()}.updated", actor=self.request.user, restaurant=self.request.tenant, obj=obj,
              metadata={"fields": sorted(serializer.validated_data)}, request=self.request)


class CategoryViewSet(TenantViewSet):
    model = Category
    serializer_class = CategorySerializer


def _snapshot(p):
    d = {f: getattr(p, f) for f in TRACKED_PRODUCT_FIELDS}
    d["variations"] = sorted((v.name, str(v.price_delta), v.is_available) for v in p.variations.all())
    d["addons"] = sorted((a.name, str(a.price), a.is_available) for a in p.addons.all())
    return {k: (str(v) if v is not None and not isinstance(v, (bool, int, list)) else v) for k, v in d.items()}


class ProductViewSet(TenantViewSet):
    model = Product
    serializer_class = ProductManageSerializer

    def get_queryset(self):
        qs = (Product.unscoped.filter(restaurant=self.request.tenant)
              .select_related("category").prefetch_related("variations", "addons"))
        p = self.request.query_params
        if p.get("archived") == "1":
            qs = qs.filter(is_archived=True)
        elif self.action == "list":
            qs = qs.filter(is_archived=False)
        if p.get("category", "").isdigit():
            qs = qs.filter(category_id=int(p["category"]))
        if q := p.get("q", "").strip():
            qs = qs.filter(name__icontains=q)
        return qs

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "request": self.request}

    def perform_create(self, serializer):
        product = serializer.save(restaurant=self.request.tenant)
        audit("product.created", actor=self.request.user, restaurant=self.request.tenant, obj=product,
              metadata={"name": product.name, "base_price": str(product.base_price)}, request=self.request)

    def perform_update(self, serializer):
        before = _snapshot(serializer.instance)
        product = serializer.save()
        product = self.get_queryset().get(pk=product.pk)
        after = _snapshot(product)
        changes = {k: [before[k], after[k]] for k in after if before[k] != after[k]}
        if changes:  # price / availability / offer changes are individually recorded with old and new values
            audit("product.updated", actor=self.request.user, restaurant=self.request.tenant, obj=product,
                  metadata={"changes": changes}, request=self.request)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        return self._set_archived(request, True)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        return self._set_archived(request, False)

    def _set_archived(self, request, value):
        product = self.get_object()
        if product.is_archived != value:
            product.is_archived = value
            product.save()
            audit("product.archived" if value else "product.restored", actor=request.user, restaurant=request.tenant,
                  obj=product, request=request)
        return Response(self.get_serializer(product).data)

    @action(detail=True, methods=["post", "delete"], parser_classes=[MultiPartParser, FormParser], url_path="image")
    def image(self, request, pk=None):
        product = self.get_object()
        if request.method == "DELETE":
            product.image.delete(save=False)
            product.image = ""
        else:
            s = ImageUploadSerializer(data=request.data)
            s.is_valid(raise_exception=True)
            product.image = s.validated_data["image"]
        product.save()
        audit("product.image_changed", actor=request.user, restaurant=request.tenant, obj=product, request=request)
        return Response(self.get_serializer(product).data)

    @action(detail=True, methods=["post"], parser_classes=[JSONParser])
    def stock(self, request, pk=None):
        s = StockAdjustSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        with transaction.atomic():
            # Row lock: two concurrent adjustments cannot both read the same quantity.
            product = Product.unscoped.select_for_update().get(pk=self.get_object().pk, restaurant=request.tenant)
            if not product.track_inventory:
                raise serializers.ValidationError({"detail": "Inventory tracking is not enabled for this product."})
            new_qty = product.stock_quantity + d["delta"]
            if new_qty < 0:
                raise serializers.ValidationError({"delta": "Stock cannot go below zero."})
            product.stock_quantity = new_qty
            product.save()
            StockMovement.objects.create(restaurant=request.tenant, product=product, delta=d["delta"], quantity_after=new_qty,
                                         reason=d["reason"], note=d["note"], actor=request.user)
            audit("inventory.adjusted", actor=request.user, restaurant=request.tenant, obj=product,
                  metadata={"delta": d["delta"], "reason": d["reason"], "after": new_qty}, request=request)
        return Response(self.get_serializer(product).data)

    @action(detail=False, methods=["get"], url_path="low-stock")
    def low_stock(self, request):
        qs = self.get_queryset().filter(track_inventory=True, stock_quantity__lte=F("low_stock_threshold"))
        return Response(self.get_serializer(qs, many=True).data)


class StockMovementViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsManagerOrAbove]
    serializer_class = StockMovementSerializer

    def get_queryset(self):
        qs = StockMovement.unscoped.filter(restaurant=self.request.tenant).select_related("product", "actor")
        if self.request.query_params.get("product", "").isdigit():
            qs = qs.filter(product_id=int(self.request.query_params["product"]))
        return qs


class ServiceViewSet(TenantViewSet):
    model = Service
    serializer_class = ServiceSerializer

    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser, FormParser], url_path="image")
    def image(self, request, pk=None):
        obj = self.get_object()
        s = ImageUploadSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        obj.image = s.validated_data["image"]
        obj.save()
        return Response(self.get_serializer(obj).data)


class GalleryViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsManagerOrAbove]
    serializer_class = GallerySerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        return GalleryImage.unscoped.filter(restaurant=self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(restaurant=self.request.tenant)

    def perform_destroy(self, instance):  # gallery photos are marketing content, not financial records
        audit("gallery.deleted", actor=self.request.user, restaurant=self.request.tenant, obj=instance, request=self.request)
        instance.image.delete(save=False)
        instance.delete()
