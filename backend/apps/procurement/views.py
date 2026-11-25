from decimal import Decimal

from django.db.models import Count, F, Sum
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManagerOrAbove, accessible_branch_ids
from apps.core.models import audit
from apps.core.pagination import StandardPagination

from . import services
from .models import UNITS, Ingredient, IngredientMovement, IngredientStock, PurchaseOrder, RecipeLine, Supplier

QTY = dict(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))


class Manage(APIView):
    permission_classes = [IsManagerOrAbove]


# ---------------------------------------------------------------- suppliers
class SupplierInput(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    contact_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    address = serializers.CharField(max_length=250, required=False, allow_blank=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)


def supplier_json(s):
    return {"id": s.pk, "name": s.name, "contact_name": s.contact_name, "phone": s.phone, "email": s.email, "address": s.address, "notes": s.notes, "is_active": s.is_active}


class SuppliersView(Manage):
    def get(self, request):
        qs = Supplier.unscoped.filter(restaurant=request.tenant)
        if request.query_params.get("active") == "1":
            qs = qs.filter(is_active=True)
        if q := request.query_params.get("q", "").strip()[:100]:
            qs = qs.filter(name__icontains=q)
        return Response([supplier_json(s) for s in qs[:500]])

    def post(self, request):
        s = SupplierInput(data=request.data)
        s.is_valid(raise_exception=True)
        if Supplier.unscoped.filter(restaurant=request.tenant, name__iexact=s.validated_data["name"].strip()).exists():
            raise serializers.ValidationError({"name": "A supplier with this name already exists."})
        sup = Supplier.objects.create(restaurant=request.tenant, **{**s.validated_data, "name": s.validated_data["name"].strip()})
        audit("supplier.created", actor=request.user, restaurant=request.tenant, obj=sup, request=request)
        return Response(supplier_json(sup), status=201)


class SupplierView(Manage):
    def _get(self, request, pk):
        s = Supplier.unscoped.filter(pk=pk, restaurant=request.tenant).first()
        if s is None:
            raise NotFound()
        return s

    def get(self, request, pk):
        return Response(supplier_json(self._get(request, pk)))

    def patch(self, request, pk):
        sup = self._get(request, pk)
        s = SupplierInput(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        name = s.validated_data.get("name")
        if name and Supplier.unscoped.filter(restaurant=request.tenant, name__iexact=name.strip()).exclude(pk=sup.pk).exists():
            raise serializers.ValidationError({"name": "A supplier with this name already exists."})
        for k, v in s.validated_data.items():
            setattr(sup, k, v.strip() if isinstance(v, str) else v)
        sup.save()
        audit("supplier.updated", actor=request.user, restaurant=request.tenant, obj=sup, metadata={"fields": sorted(s.validated_data)}, request=request)
        return Response(supplier_json(sup))


# ---------------------------------------------------------------- ingredients and stock
class IngredientInput(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    unit = serializers.ChoiceField(choices=[u for u, _ in UNITS])
    low_stock_threshold = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0"), required=False)
    is_active = serializers.BooleanField(required=False)


def ingredient_rows(request, qs):
    allowed = accessible_branch_ids(request)
    stocks = {}
    for st in IngredientStock.unscoped.filter(restaurant=request.tenant, branch_id__in=allowed, ingredient__in=qs).select_related("branch"):
        stocks.setdefault(st.ingredient_id, []).append(st)
    out = []
    for i in qs:
        rows = stocks.get(i.pk, [])
        total = sum((r.quantity for r in rows), Decimal("0"))
        out.append({"id": i.pk, "name": i.name, "unit": i.unit, "low_stock_threshold": str(i.low_stock_threshold), "last_unit_cost": str(i.last_unit_cost), "is_active": i.is_active,
                    "total": str(total), "low": any(r.quantity <= i.low_stock_threshold for r in rows) if rows else i.low_stock_threshold > 0,
                    "branches": [{"branch_id": r.branch_id, "branch": r.branch.name, "quantity": str(r.quantity), "low": r.quantity <= i.low_stock_threshold} for r in rows]})
    return out


class IngredientsView(Manage):
    def get(self, request):
        qs = Ingredient.unscoped.filter(restaurant=request.tenant)
        if request.query_params.get("active") == "1":
            qs = qs.filter(is_active=True)
        if q := request.query_params.get("q", "").strip()[:100]:
            qs = qs.filter(name__icontains=q)
        rows = ingredient_rows(request, list(qs[:1000]))
        if request.query_params.get("low") == "1":
            rows = [r for r in rows if r["low"]]
        return Response(rows)

    def post(self, request):
        s = IngredientInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        if Ingredient.unscoped.filter(restaurant=request.tenant, name__iexact=d["name"].strip()).exists():
            raise serializers.ValidationError({"name": "This ingredient already exists."})
        ing = Ingredient.objects.create(restaurant=request.tenant, **{**d, "name": d["name"].strip()})
        audit("ingredient.created", actor=request.user, restaurant=request.tenant, obj=ing, request=request)
        return Response(ingredient_rows(request, [ing])[0], status=201)


class IngredientView(Manage):
    def patch(self, request, pk):
        ing = Ingredient.unscoped.filter(pk=pk, restaurant=request.tenant).first()
        if ing is None:
            raise NotFound()
        s = IngredientInput(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        name = s.validated_data.get("name")
        if name and Ingredient.unscoped.filter(restaurant=request.tenant, name__iexact=name.strip()).exclude(pk=ing.pk).exists():
            raise serializers.ValidationError({"name": "This ingredient already exists."})
        if "unit" in s.validated_data and s.validated_data["unit"] != ing.unit and ing.stocks.filter(quantity__gt=0).exists():
            raise serializers.ValidationError({"unit": "The unit cannot change while stock exists."})
        for k, v in s.validated_data.items():
            setattr(ing, k, v.strip() if isinstance(v, str) else v)
        ing.save()
        return Response(ingredient_rows(request, [ing])[0])


class AdjustInput(serializers.Serializer):
    ingredient_id = serializers.IntegerField()
    branch_id = serializers.IntegerField()
    mode = serializers.ChoiceField(choices=["delta", "set"])
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3)
    reason = serializers.ChoiceField(choices=["waste", "adjustment", "opening"])
    note = serializers.CharField(max_length=200)


class AdjustView(Manage):
    def post(self, request):
        s = AdjustInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        if d["mode"] == "set" and d["quantity"] < 0:
            raise serializers.ValidationError({"quantity": "A counted quantity cannot be negative."})
        st = services.adjust(request, d["ingredient_id"], d["branch_id"], d["mode"], d["quantity"], d["reason"], d["note"])
        return Response({"ingredient_id": st.ingredient_id, "branch_id": st.branch_id, "quantity": str(st.quantity)})


class MovementsView(ListAPIView):
    permission_classes = [IsManagerOrAbove]
    pagination_class = StandardPagination

    def get(self, request, *a, **k):
        qs = IngredientMovement.unscoped.filter(restaurant=request.tenant, branch_id__in=accessible_branch_ids(request)).select_related("ingredient", "branch", "actor")
        if request.query_params.get("ingredient", "").isdigit():
            qs = qs.filter(ingredient_id=int(request.query_params["ingredient"]))
        page = self.paginate_queryset(qs)
        return self.get_paginated_response([{"id": m.pk, "ingredient": m.ingredient.name, "unit": m.ingredient.unit, "branch": m.branch.name, "delta": str(m.delta), "quantity_after": str(m.quantity_after),
                                             "reason": m.reason, "note": m.note, "actor": (m.actor.full_name or m.actor.email) if m.actor else None, "created_at": m.created_at} for m in page])


# ---------------------------------------------------------------- recipes
class RecipeInput(serializers.Serializer):
    ingredient_id = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=4, min_value=Decimal("0.0001"))


class RecipeView(Manage):
    def get(self, request, product_id):
        from apps.catalog.models import Product

        if not Product.unscoped.filter(pk=product_id, restaurant=request.tenant).exists():
            raise NotFound()
        rl = RecipeLine.unscoped.filter(restaurant=request.tenant, product_id=product_id).select_related("ingredient")
        return Response([{"ingredient_id": r.ingredient_id, "ingredient": r.ingredient.name, "unit": r.ingredient.unit, "quantity": str(r.quantity)} for r in rl])

    def put(self, request, product_id):
        s = RecipeInput(data=request.data.get("lines", []), many=True)
        s.is_valid(raise_exception=True)
        services.set_recipe(request, product_id, [dict(x) for x in s.validated_data])
        return self.get(request, product_id)


# ---------------------------------------------------------------- purchase orders
class LineInput(serializers.Serializer):
    ingredient_id = serializers.IntegerField()
    quantity = serializers.DecimalField(**QTY)
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=4, min_value=Decimal("0"))


class POInput(serializers.Serializer):
    branch_id = serializers.IntegerField()
    supplier_id = serializers.IntegerField()
    expected_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)
    lines = LineInput(many=True)


class POPatch(serializers.Serializer):
    supplier_id = serializers.IntegerField(required=False)
    expected_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)
    lines = LineInput(many=True, required=False)


def po_json(po, detail=True):
    d = {"id": po.pk, "number": po.number, "status": po.status, "supplier": po.supplier.name, "supplier_id": po.supplier_id, "branch": po.branch.name, "branch_id": po.branch_id,
         "expected_date": po.expected_date, "total": str(po.total), "currency": po.currency, "created_at": po.created_at, "ordered_at": po.ordered_at, "cancel_reason": po.cancel_reason, "notes": po.notes}
    if detail:
        d["lines"] = [{"id": l.pk, "ingredient_id": l.ingredient_id, "ingredient": l.ingredient.name, "unit": l.ingredient.unit, "quantity": str(l.quantity), "unit_cost": str(l.unit_cost), "received": str(l.received)}
                      for l in po.lines.select_related("ingredient")]
    return d


class POListView(Manage):
    def get(self, request):
        qs = PurchaseOrder.unscoped.filter(restaurant=request.tenant, branch_id__in=accessible_branch_ids(request)).select_related("supplier", "branch")
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        return Response([po_json(p, detail=False) for p in qs[:200]])

    def post(self, request):
        s = POInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        po = services.create_po(request, {**d, "lines": [dict(l) for l in d["lines"]]})
        return Response(po_json(PurchaseOrder.unscoped.select_related("supplier", "branch").get(pk=po.pk)), status=201)


class PODetailView(Manage):
    def _get(self, request, pk):
        po = PurchaseOrder.unscoped.select_related("supplier", "branch").filter(pk=pk, restaurant=request.tenant, branch_id__in=accessible_branch_ids(request)).first()
        if po is None:
            raise NotFound()
        return po

    def get(self, request, pk):
        return Response(po_json(self._get(request, pk)))

    def patch(self, request, pk):
        s = POPatch(data=request.data)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        if "lines" in d:
            d["lines"] = [dict(l) for l in d["lines"]]
        services.update_po(request, pk, d)
        return Response(po_json(self._get(request, pk)))


class POActionView(Manage):
    def post(self, request, pk, act):
        if act == "order":
            services.place_po(request, pk)
        elif act == "receive":
            class In(serializers.Serializer):
                line_id = serializers.IntegerField()
                quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0"))

            s = In(data=request.data.get("lines", []), many=True)
            s.is_valid(raise_exception=True)
            services.receive_po(request, pk, [dict(x) for x in s.validated_data])
        elif act == "cancel":
            services.cancel_po(request, pk, str(request.data.get("reason", "")))
        else:
            raise NotFound()
        po = PurchaseOrder.unscoped.select_related("supplier", "branch").get(pk=pk)
        return Response(po_json(po))


class SummaryView(Manage):
    """Counts for the dashboard: low-stock ingredients and open purchase orders."""

    def get(self, request):
        rows = ingredient_rows(request, list(Ingredient.unscoped.filter(restaurant=request.tenant, is_active=True)))
        open_po = PurchaseOrder.unscoped.filter(restaurant=request.tenant, branch_id__in=accessible_branch_ids(request), status__in=["ordered", "partially_received"])
        return Response({"low_stock": [r for r in rows if r["low"]][:20], "low_stock_count": sum(1 for r in rows if r["low"]), "open_orders": open_po.count(),
                         "open_orders_value": str((open_po.aggregate(t=Sum("total"))["t"] or Decimal("0")).quantize(Decimal("0.01")))})


_ = (Count, F)
