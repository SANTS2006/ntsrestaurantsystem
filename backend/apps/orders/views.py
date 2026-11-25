from django.db.models import Q
from django.utils.dateparse import parse_date
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.permissions import IsCustomerOfTenant, IsStaff, accessible_branch_ids, effective_role
from apps.core.idempotency import run_idempotent
from apps.customers.models import CustomerAddress

from .models import Order, Status
from .pricing import price_cart
from .serializers import (CheckoutSerializer, KitchenOrderSerializer, OrderDetailSerializer, OrderListSerializer, QuoteSerializer,
                          StaffOrderDetailSerializer, TransitionSerializer)
from .services import create_order, customer_cancel, label, transition_order


def _require_tenant(request):
    if request.tenant is None:
        raise serializers.ValidationError({"detail": "Orders are only available on a restaurant website."})


class QuoteView(APIView):
    """Authoritative cart totals for display. Public (prices are public) and throttled."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        _require_tenant(request)
        s = QuoteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        quote = price_cart(request.tenant, s.validated_data["items"], s.validated_data["fulfilment"])
        return Response(quote.as_dict())


class CheckoutView(APIView):
    permission_classes = [IsAuthenticated, IsCustomerOfTenant]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        _require_tenant(request)
        s = CheckoutSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)
        if data["fulfilment"] == "delivery":
            if data["address_id"]:  # only the caller's own saved address, in this restaurant
                a = CustomerAddress.unscoped.filter(pk=data["address_id"], restaurant=request.tenant, user=request.user).first()
                if a is None:
                    raise serializers.ValidationError({"address_id": "Address not found."})
                data["address_snapshot"] = {"recipient_name": a.recipient_name, "phone": a.phone, "line1": a.line1,
                                            "line2": a.line2, "city": a.city, "delivery_notes": a.delivery_notes}
            elif data["address"]:
                data["address_snapshot"] = dict(data["address"])
        data["items"] = [dict(i, addons=[dict(a) for a in i["addons"]]) for i in data["items"]]

        def handler():
            order = create_order(request, data, customer=request.user)
            order = Order.unscoped.prefetch_related("items", "history", "payments__receipt").select_related("branch").get(pk=order.pk)
            return 201, dict(OrderDetailSerializer(order, context={"request": request}).data)

        status, body = run_idempotent(request, "order.create", request.headers.get("Idempotency-Key", ""), request.data, handler)
        return Response(body, status=status)


class MyOrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """A customer's own orders. The queryset is filtered by the authenticated user: other ids are simply 404."""

    permission_classes = [IsAuthenticated, IsCustomerOfTenant]

    def get_queryset(self):
        return (Order.unscoped.filter(restaurant=self.request.tenant, customer=self.request.user)
                .select_related("branch").prefetch_related("items", "history", "payments__receipt"))

    def get_serializer_class(self):
        return OrderListSerializer if self.action == "list" else OrderDetailSerializer

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order, outcome = customer_cancel(request, self.get_object().pk, str(request.data.get("reason", ""))[:300])
        order = self.get_queryset().get(pk=order.pk)
        return Response({"outcome": outcome, "order": OrderDetailSerializer(order, context={"request": request}).data})


class StaffOrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Orders for the branches the staff member may access (admins: all branches of the restaurant)."""

    permission_classes = [IsStaff]

    def get_queryset(self):
        qs = (Order.unscoped.filter(restaurant=self.request.tenant, branch_id__in=accessible_branch_ids(self.request))
              .select_related("branch").prefetch_related("items", "history", "payments__receipt"))
        p = self.request.query_params
        if p.get("status") in Status.values:
            qs = qs.filter(status=p["status"])
        if p.get("active") == "1":
            qs = qs.exclude(status__in=[Status.COMPLETED, Status.CANCELLED, Status.REFUNDED])
        if p.get("branch", "").isdigit():
            qs = qs.filter(branch_id=int(p["branch"]))
        if q := p.get("q", "").strip():
            qs = qs.filter(Q(number__icontains=q) | Q(contact_name__icontains=q) | Q(contact_phone__icontains=q))
        if (d := parse_date(p.get("date_from", ""))):
            qs = qs.filter(created_at__date__gte=d)
        if (d := parse_date(p.get("date_to", ""))):
            qs = qs.filter(created_at__date__lte=d)
        return qs

    def get_serializer_class(self):
        if self.action == "list":
            return KitchenOrderSerializer if self.request.query_params.get("include") == "items" else OrderListSerializer
        return StaffOrderDetailSerializer

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "role": effective_role(self.request)}

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        s = TransitionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        order = self.get_object()  # branch-scoped lookup first: other branches' ids are 404
        if s.validated_data["status"] not in Status.values:
            raise serializers.ValidationError({"status": "Unknown status."})
        transition_order(request, order.pk, s.validated_data["status"], role=effective_role(request), note=s.validated_data["note"])
        return Response(self.get_serializer(self.get_queryset().get(pk=order.pk)).data)

    @action(detail=False, methods=["get"], url_path="statuses")
    def statuses(self, request):
        return Response([{"status": s, "label": label(s)} for s in Status.values])
