import io
from decimal import Decimal

import qrcode
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.permissions import IsCashierOrAbove, IsManagerOrAbove, accessible_branch_ids, effective_role
from apps.cashier.views import apply_payment_choice
from apps.catalog.public_views import _build_menu
from apps.core.idempotency import run_idempotent
from apps.core.models import audit
from apps.orders.models import Order
from apps.orders.pricing import LineInput
from apps.orders.serializers import OrderDetailSerializer
from apps.orders.services import create_order
from apps.payments.views import payment_json

from . import services
from .models import DiningTable, QRMenuRequest, new_token


# ======================= public (diners) ===============================================================
class PublicQRBase(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def tenant_required(self, request):
        if request.tenant is None:
            raise NotFound()


class PublicTableView(PublicQRBase):
    """What a scanned QR code opens: the restaurant, branch, table and the currently available menu. Nothing about staff or customers."""

    def get(self, request, token):
        self.tenant_required(request)
        t = services.table_for_token(request.tenant, token)
        st = request.tenant.get_settings()
        return Response({
            "restaurant": {"name": request.tenant.name, "primary_color": request.tenant.primary_color, "secondary_color": request.tenant.secondary_color},
            "branch": t.branch.name, "table": t.label, "currency": st.currency,
            "can_request": st.qr_guest_orders_allowed, "identification": st.qr_identification,
            "menu": _build_menu(request, request.tenant),
        })


class RequestInput(serializers.Serializer):
    items = LineInput(many=True)
    customer_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    customer_phone = serializers.RegexField(r"^[0-9+()\-\s]{6,30}$", required=False, allow_blank=True, default="", error_messages={"invalid": "Enter a valid phone number."})
    notes = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    website = serializers.CharField(required=False, allow_blank=True, default="")  # honeypot: humans never fill this in

    def validate_website(self, v):
        if v:
            raise serializers.ValidationError("Invalid request.")
        return v


class PublicRequestCreateView(PublicQRBase):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "qr"

    def post(self, request, token):
        self.tenant_required(request)
        s = RequestInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        d["items"] = [dict(i, addons=[dict(a) for a in i["addons"]]) for i in d["items"]]
        r = services.submit_request(request, token, d)
        return Response({"public_id": str(r.public_id), "status": r.status, "table": r.table.label, "total": r.summary["total"],
                         "message": "Your request was sent to the staff. It is not an order until a cashier confirms it."}, status=201)


class PublicRequestStatusView(PublicQRBase):
    def get(self, request, token, public_id):
        self.tenant_required(request)
        t = services.table_for_token(request.tenant, token)
        r = QRMenuRequest.unscoped.filter(public_id=public_id, table=t).first()
        if r is None:
            raise NotFound()
        return Response({"status": r.status, "reject_reason": r.reject_reason if r.status == "rejected" else ""})  # nothing else is exposed


# ======================= staff: tables ==================================================================
class TableSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    qr_url = serializers.SerializerMethodField()

    class Meta:
        model = DiningTable
        fields = ["id", "label", "seats", "is_active", "branch", "branch_name", "qr_url", "qr_regenerated_at"]
        read_only_fields = ["id", "qr_regenerated_at"]

    def get_qr_url(self, t):
        return f"{self.context['request'].tenant.public_url}/t/{t.qr_token}"

    def validate_branch(self, b):
        if b.restaurant_id != self.context["request"].tenant.pk or b.pk not in accessible_branch_ids(self.context["request"]):
            raise serializers.ValidationError("Choose one of your branches.")
        return b

    def validate(self, a):
        branch = a.get("branch") or getattr(self.instance, "branch", None)
        label = a.get("label", getattr(self.instance, "label", None))
        qs = DiningTable.unscoped.filter(branch=branch, label__iexact=label)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError({"label": "This branch already has a table with that name."})
        return a


class TableViewSet(viewsets.ModelViewSet):
    serializer_class = TableSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]  # tables are disabled, never deleted

    def get_permissions(self):
        return [IsCashierOrAbove()] if self.action in ("list", "retrieve") else [IsManagerOrAbove()]

    def get_queryset(self):
        return (DiningTable.unscoped.filter(restaurant=self.request.tenant, branch_id__in=accessible_branch_ids(self.request))
                .select_related("branch"))

    def perform_create(self, serializer):
        t = serializer.save(restaurant=self.request.tenant)
        audit("table.created", actor=self.request.user, restaurant=self.request.tenant, obj=t, request=self.request)

    def perform_update(self, serializer):
        t = serializer.save()
        audit("table.updated", actor=self.request.user, restaurant=self.request.tenant, obj=t,
              metadata={"fields": sorted(serializer.validated_data)}, request=self.request)

    @action(detail=True, methods=["post"])
    def regenerate(self, request, pk=None):
        """Issue a new QR token: every printed copy of the old code stops working at once."""
        t = self.get_object()
        t.qr_token, t.qr_regenerated_at = new_token(), timezone.now()
        t.save(update_fields=["qr_token", "qr_regenerated_at", "updated_at"])
        audit("table.qr_regenerated", actor=request.user, restaurant=request.tenant, obj=t, request=request)
        return Response(self.get_serializer(t).data)

    @action(detail=True, methods=["post"])
    def disable(self, request, pk=None):
        return self._toggle(request, False)

    @action(detail=True, methods=["post"])
    def enable(self, request, pk=None):
        return self._toggle(request, True)

    def _toggle(self, request, value):
        t = self.get_object()
        if t.is_active != value:
            t.is_active = value
            t.save(update_fields=["is_active", "updated_at"])
            audit("table.enabled" if value else "table.disabled", actor=request.user, restaurant=request.tenant, obj=t, request=request)
        return Response(self.get_serializer(t).data)

    @action(detail=True, methods=["get"], url_path="qr")
    def qr_image(self, request, pk=None):
        """PNG of the table's QR code (staff only: the token is a credential for creating requests at this table)."""
        t = self.get_object()
        img = qrcode.make(f"{request.tenant.public_url}/t/{t.qr_token}", box_size=10, border=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        resp = HttpResponse(buf.getvalue(), content_type="image/png")
        resp["Cache-Control"] = "private, no-store"
        resp["Content-Disposition"] = f'inline; filename="table-{t.pk}.png"'
        return resp


# ======================= staff: requests ================================================================
class RequestViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsCashierOrAbove]

    def get_queryset(self):
        qs = (QRMenuRequest.unscoped.filter(restaurant=self.request.tenant, branch_id__in=accessible_branch_ids(self.request))
              .select_related("branch", "table"))
        st = self.request.query_params.get("status")
        if st in QRMenuRequest.Status.values:
            qs = qs.filter(status=st)
        return qs

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response([services.request_json(r) for r in page])

    def retrieve(self, request, *args, **kwargs):
        return Response(services.request_json(self.get_object()))

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        reason = str(request.data.get("reason", "")).strip()
        r = services.reject_request(request, pk, reason, accessible_branch_ids(request))
        return Response(services.request_json(r))

    @action(detail=True, methods=["post"])
    def convert(self, request, pk=None):
        """Turn a request into an official order and take payment (cash / mobile money) or leave it to pay later."""
        s = ConvertSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        branches, role = accessible_branch_ids(request), effective_role(request)

        def handler():
            r = (QRMenuRequest.unscoped.select_for_update(of=("self",)).select_related("branch", "table")
                 .filter(pk=pk, restaurant=request.tenant, branch_id__in=branches).first())
            if r is None:
                raise NotFound()
            if r.status != QRMenuRequest.Status.NEW:
                raise serializers.ValidationError({"detail": "This request was already handled."})
            data = {"items": r.items, "fulfilment": "dine_in", "branch_id": r.branch_id, "contact_name": r.customer_name or r.table.label,
                    "contact_phone": r.customer_phone, "contact_email": "", "notes": (f"{r.table.label}. " + r.notes)[:300],
                    "payment_method": "mobile_money" if d["payment"] == "mobile_money" else "cash", "address_snapshot": {}}
            order = create_order(request, data, customer=None, source="qr", cashier=request.user, role=role, table=r.table)
            payment, change = apply_payment_choice(request, order, d["payment"], d["amount_received"], d["payer_phone"] or r.customer_phone, branches)
            r.status, r.order, r.handled_by, r.handled_at = QRMenuRequest.Status.CONVERTED, order, request.user, timezone.now()
            r.save()
            audit("qr.request_converted", actor=request.user, restaurant=request.tenant, obj=r, metadata={"order": order.number}, request=request)
            services.notify_branch(request.tenant.pk, r.branch_id, {"type": "qr.request.updated", "id": r.pk, "status": r.status})
            order = Order.unscoped.prefetch_related("items", "history", "payments__receipt").select_related("branch").get(pk=order.pk)
            body = {"order": dict(OrderDetailSerializer(order, context={"request": request}).data)}
            if payment is not None:
                pj = payment_json(payment)
                pj["receipt_id"] = payment.receipt.pk if hasattr(payment, "receipt") else None
                body.update(payment=pj, change_given=change)
            return 201, body

        status, body = run_idempotent(request, f"qr.convert:{pk}", request.headers.get("Idempotency-Key", ""), request.data, handler)
        return Response(body, status=status)


class ConvertSerializer(serializers.Serializer):
    payment = serializers.ChoiceField(choices=["cash", "mobile_money", "pay_later"])
    amount_received = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), required=False, allow_null=True, default=None)
    payer_phone = serializers.RegexField(r"^[0-9+()\-\s]{6,30}$", required=False, allow_blank=True, default="")

    def validate(self, a):
        if a["payment"] == "cash" and a["amount_received"] is None:
            raise serializers.ValidationError({"amount_received": "Enter the cash received."})
        return a

