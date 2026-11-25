"""Staff customer directory: managers and administrators look up customers of their restaurant.

Administrators see every customer of the restaurant; managers only customers who ordered at one of their branches.
Contact details are personal data: every profile view is audited and notes are append-only.
"""
from decimal import Decimal

from django.db.models import Count, DecimalField, Max, Q, Sum
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Membership, Role
from apps.accounts.permissions import IsManagerOrAbove, accessible_branch_ids, effective_role
from apps.core.models import audit
from apps.core.pagination import StandardPagination
from apps.orders.models import Order

from .models import CustomerNote

DEAD = ["cancelled", "refunded"]


def scoped_customers(request):
    qs = Membership.objects.filter(restaurant=request.tenant, role=Role.CUSTOMER, is_active=True).select_related("user")
    if effective_role(request) in (Role.RESTAURANT_ADMIN, Role.PLATFORM_ADMIN):
        return qs
    ids = Order.unscoped.filter(restaurant=request.tenant, branch_id__in=accessible_branch_ids(request), customer__isnull=False).values("customer_id")
    return qs.filter(user_id__in=ids)


def stats_for(request, user_ids):
    o = Order.unscoped.filter(restaurant=request.tenant, customer_id__in=user_ids)
    if effective_role(request) not in (Role.RESTAURANT_ADMIN, Role.PLATFORM_ADMIN):
        o = o.filter(branch_id__in=accessible_branch_ids(request))  # a manager sees only their own branches' activity
    rows = o.exclude(status__in=DEAD).values("customer_id").annotate(n=Count("id"), spent=Sum("total", output_field=DecimalField()), last=Max("created_at"))
    return {r["customer_id"]: r for r in rows}


class DirectoryRow(serializers.Serializer):
    pass


class CustomerList(ListAPIView):
    permission_classes = [IsManagerOrAbove]
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = scoped_customers(self.request)
        if q := self.request.query_params.get("q", "").strip()[:100]:
            qs = qs.filter(Q(user__full_name__icontains=q) | Q(user__email__icontains=q) | Q(user__phone__icontains=q))
        return qs.order_by("user__full_name", "id")

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        stats = stats_for(request, [m.user_id for m in page])
        rows = []
        for m in page:
            st = stats.get(m.user_id)
            rows.append({"id": m.user_id, "name": m.user.full_name or m.user.email, "email": m.user.email, "phone": m.user.phone, "joined": m.created_at if hasattr(m, "created_at") else None,
                         "orders": st["n"] if st else 0, "spent": str((st["spent"] or Decimal("0")).quantize(Decimal("0.01"))) if st else "0.00", "last_order": st["last"] if st else None})
        return self.get_paginated_response(rows)


class NoteInput(serializers.Serializer):
    text = serializers.CharField(max_length=500)

    def validate_text(self, v):
        v = v.strip()
        if len(v) < 2:
            raise serializers.ValidationError("Write a note.")
        return v


class CustomerDetail(APIView):
    permission_classes = [IsManagerOrAbove]

    def _member(self, request, pk):
        m = scoped_customers(request).filter(user_id=pk).first()
        if m is None:
            raise NotFound()
        return m

    def get(self, request, pk):
        m = self._member(request, pk)
        st = stats_for(request, [m.user_id]).get(m.user_id)
        orders = Order.unscoped.filter(restaurant=request.tenant, customer_id=m.user_id).select_related("branch").order_by("-created_at")
        if effective_role(request) not in (Role.RESTAURANT_ADMIN, Role.PLATFORM_ADMIN):
            orders = orders.filter(branch_id__in=accessible_branch_ids(request))
        notes = CustomerNote.unscoped.filter(restaurant=request.tenant, customer_id=m.user_id).select_related("author")[:50]
        audit("customer.viewed", actor=request.user, restaurant=request.tenant, obj=m.user, request=request)
        return Response({
            "id": m.user_id, "name": m.user.full_name or m.user.email, "email": m.user.email, "phone": m.user.phone,
            "orders": st["n"] if st else 0, "spent": str((st["spent"] or Decimal("0")).quantize(Decimal("0.01"))) if st else "0.00", "last_order": st["last"] if st else None,
            "recent_orders": [{"id": o.pk, "number": o.number, "status": o.status, "total": str(o.total), "branch": o.branch.name, "created_at": o.created_at} for o in orders[:10]],
            "notes": [{"id": n.pk, "text": n.text, "author": (n.author.full_name or n.author.email) if n.author else None, "created_at": n.created_at} for n in notes]})

    def post(self, request, pk):
        m = self._member(request, pk)
        s = NoteInput(data=request.data)
        s.is_valid(raise_exception=True)
        n = CustomerNote.objects.create(restaurant=request.tenant, customer=m.user, author=request.user, text=s.validated_data["text"])
        audit("customer.note_added", actor=request.user, restaurant=request.tenant, obj=n, metadata={"customer": m.user_id}, request=request)
        return Response({"id": n.pk, "text": n.text, "author": request.user.full_name or request.user.email, "created_at": n.created_at}, status=201)
