import base64
import io
import json
from decimal import Decimal

import qrcode

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.permissions import (IsCashierOrAbove, IsCustomerOfTenant, IsManagerOrAbove, accessible_branch_ids,
                                       effective_role)
from apps.core.idempotency import run_idempotent
from apps.core.models import audit
from apps.orders.models import Order

from . import services
from .receipt_pdf import render_pdf
from .models import Payment, PaymentEvent, Receipt
from .providers import IgnoredEvent, ProviderError, get_provider


def _key(request):
    return request.headers.get("Idempotency-Key", "")


def payment_json(p, redirect_url=""):
    waiting = p.status == Payment.Status.PENDING  # only a payment still waiting can be (re)opened or dialled
    checkout = p.checkout_url if waiting else ""
    return {"checkout_url": checkout, "ussd_code": p.ussd_code if waiting else "", "id": p.pk, "reference": p.reference, "order_id": p.order_id, "method": p.method, "status": p.status,
            "amount": str(p.amount), "currency": p.currency, "redirect_url": redirect_url or getattr(p, "redirect_url", "") or checkout,
            "provider": p.provider, "paid_at": p.paid_at.isoformat() if p.paid_at else None, "failure_reason": p.failure_reason,
            "receipt_id": p.receipt.pk if hasattr(p, "receipt") else None}


class InitiateSerializer(serializers.Serializer):
    order_id = serializers.IntegerField()
    phone = serializers.RegexField(r"^[0-9+()\-\s]{6,30}$", error_messages={"invalid": "Enter a valid phone number."})


class InitiateView(APIView):
    permission_classes = [IsAuthenticated, IsCustomerOfTenant]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        s = InitiateSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        def handler():
            p = services.initiate_online_payment(request, s.validated_data["order_id"], s.validated_data["phone"])
            return 201, payment_json(p)

        status, body = run_idempotent(request, "payment.initiate", _key(request), request.data, handler)
        return Response(body, status=status)


class MyPaymentStatusView(APIView):
    """Customer polls this after paying. It asks the provider (server-side) and returns the verified state."""

    permission_classes = [IsAuthenticated, IsCustomerOfTenant]

    def get(self, request, pk):
        p = Payment.unscoped.filter(pk=pk, restaurant=request.tenant, order__customer=request.user).first()
        if p is None:
            raise NotFound()
        if p.status == Payment.Status.PENDING:
            p = services.settle_payment(p.pk, source="poll")
        return Response(payment_json(p))


def dial_link(code):
    return "tel:" + code.replace("#", "%23")


def qr_data_url(text):
    """PNG of `text` as a data: URL, so the till can show the payment page for the customer to scan."""
    img = qrcode.make(text, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


class StaffPaymentStatusView(APIView):
    """The till follows a mobile-money payment: asks the provider (server-side), returns the verified state and, while it is
    still pending, a QR code of the payment page for the customer to scan. Limited to the staff member's own branches."""

    permission_classes = [IsCashierOrAbove]

    def get(self, request, pk):
        p = Payment.unscoped.filter(pk=pk, restaurant=request.tenant, branch_id__in=accessible_branch_ids(request)).first()
        if p is None:
            raise NotFound()
        if p.status == Payment.Status.PENDING and p.provider != "cash":
            p = services.settle_payment(p.pk, source="poll")
        data = payment_json(p)
        data["order_number"] = p.order.number
        # the code is for the customer's phone: scanning opens the payment page, or the dialler with the code filled in
        target = data["checkout_url"] or (dial_link(data["ussd_code"]) if data["ussd_code"] else "")
        data["qr"] = qr_data_url(target) if target else ""
        return Response(data)


class StaffMobileMoneyView(APIView):
    permission_classes = [IsCashierOrAbove]

    def post(self, request):
        s = InitiateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        branches = accessible_branch_ids(request)

        def handler():
            p = services.start_staff_mobile_money(request, s.validated_data["order_id"], s.validated_data["phone"], branches)
            return 201, payment_json(p)

        status, body = run_idempotent(request, "payment.staff_momo", _key(request), request.data, handler)
        return Response(body, status=status)


class CashSerializer(serializers.Serializer):
    order_id = serializers.IntegerField()
    amount_received = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))


class CashView(APIView):
    permission_classes = [IsCashierOrAbove]

    def post(self, request):
        s = CashSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        branches = accessible_branch_ids(request)

        def handler():
            p = services.record_cash_payment(request, s.validated_data["order_id"], s.validated_data["amount_received"], branches)
            d = payment_json(p)
            d["receipt_id"] = p.receipt.pk
            d["change_given"] = str(p.change_given)
            return 201, d

        status, body = run_idempotent(request, "payment.cash", _key(request), request.data, handler)
        return Response(body, status=status)


class RefundSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    reason = serializers.CharField(min_length=3, max_length=300)
    manual_reference = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")  # providers without a refund API


class RefundView(APIView):
    permission_classes = [IsManagerOrAbove]

    def post(self, request, pk):
        s = RefundSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        branches, role = accessible_branch_ids(request), effective_role(request)

        def handler():
            r = services.refund_payment(request, pk, s.validated_data["amount"], s.validated_data["reason"], branches, role, s.validated_data["manual_reference"])
            return 201, {"id": r.pk, "reference": r.reference, "amount": str(r.amount), "status": r.status, "order_id": r.order_id}

        status, body = run_idempotent(request, f"payment.refund:{pk}", _key(request), request.data, handler)
        return Response(body, status=status)


class StaffPaymentViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Payment history and unresolved transactions for investigation (manager/admin, branch-scoped)."""

    permission_classes = [IsManagerOrAbove]

    def get_queryset(self):
        qs = (Payment.unscoped.filter(restaurant=self.request.tenant, branch_id__in=accessible_branch_ids(self.request))
              .select_related("order", "recorded_by"))
        p = self.request.query_params
        if p.get("status") in Payment.Status.values:
            qs = qs.filter(status=p["status"])
        if p.get("order", "").isdigit():
            qs = qs.filter(order_id=int(p["order"]))
        return qs

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        rows = [{**payment_json(p), "order_number": p.order.number, "created_at": p.created_at,
                 "recorded_by": p.recorded_by.email if p.recorded_by else None, "refunded": str(services.refunded_total(p))} for p in page]
        return self.get_paginated_response(rows)


# ---- receipts ----------------------------------------------------------------------------------
def _receipt_for(request, pk):
    qs = Receipt.unscoped.filter(pk=pk, restaurant=request.tenant).select_related("order")
    role = effective_role(request)
    if role == "customer":
        qs = qs.filter(order__customer=request.user)
    elif role in ("platform_admin", "restaurant_admin", "manager", "cashier", "waiter", "waitress"):
        qs = qs.filter(branch_id__in=accessible_branch_ids(request))
    else:
        qs = qs.none()  # kitchen/delivery staff and strangers never see receipts
    r = qs.first()
    if r is None:
        raise NotFound()
    return r


class ReceiptView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        r = _receipt_for(request, pk)
        data = receipt_view_data(r)
        return Response({"id": r.pk, "number": r.number, **data, "qr": qr_data_url(data["website"])})


def receipt_view_data(receipt):
    """The stored snapshot plus what only presentation needs. Receipts issued before a field existed fall back to the restaurant's
    current website and footer; the recorded figures are never changed."""
    restaurant = receipt.restaurant
    data = dict(receipt.data)
    data.setdefault("website", restaurant.public_url)
    data.setdefault("footer", restaurant.get_settings().receipt_footer)
    data.setdefault("table", receipt.order.table_label)
    return data


class ReceiptPdfView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        r = _receipt_for(request, pk)
        audit("receipt.downloaded", actor=request.user, restaurant=request.tenant, obj=r, request=request)
        resp = HttpResponse(render_pdf(receipt_view_data(r), r.restaurant), content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="{r.number}.pdf"'
        return resp


# ---- webhooks ----------------------------------------------------------------------------------
class WebhookView(APIView):
    """Provider callbacks. The signature is verified, the event is stored once (replays are ignored), and the
    payment is then settled by asking the provider itself, so the body of the webhook is never trusted."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request, provider_name):
        try:
            provider = get_provider(provider_name)
        except ProviderError:
            raise NotFound()
        raw = request.body
        if not provider.verify_webhook(request.headers, raw):
            audit("payment.webhook_rejected", metadata={"provider": provider_name}, request=request)
            return Response({"success": False, "error": {"code": "invalid_signature", "message": "Invalid signature."}}, status=401)
        try:
            body = json.loads(raw)
            event = provider.parse_event(body)
        except IgnoredEvent:
            return Response({"success": True, "data": {"ignored": True}})  # a valid, signed event we do not act on
        except (ValueError, KeyError, TypeError):
            return Response({"success": False, "error": {"code": "bad_event", "message": "Unrecognised event."}}, status=400)
        try:
            with transaction.atomic():
                record = PaymentEvent.objects.create(provider=provider_name, event_id=event.event_id, event_type=event.event_type,
                                                     provider_ref=event.provider_ref, payload=body)
        except IntegrityError:
            return Response({"success": True, "data": {"duplicate": True}})  # replay: acknowledged, nothing re-processed
        payment = Payment.unscoped.filter(provider=provider_name, provider_ref=event.provider_ref).first()
        if payment is not None:
            record.payment = payment
            services.settle_payment(payment.pk, source="webhook")
        record.processed = payment is not None
        record.save(update_fields=["payment", "processed"])
        return Response({"success": True, "data": {"processed": record.processed}})


# ---- development simulator (never reachable in production) ---------------------------------------
class SimulateView(APIView):
    """Dev only: lets a developer 'pay' with the simulated provider and delivers a signed webhook to ourselves."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        if not settings.DEBUG or settings.PAYMENT_PROVIDER != "simulated":
            raise NotFound()
        provider = get_provider("simulated")
        ref, outcome = str(request.data.get("provider_ref", "")), str(request.data.get("outcome", "succeeded"))
        if outcome not in ("succeeded", "failed"):
            raise serializers.ValidationError({"outcome": "succeeded or failed"})
        try:
            provider.set_outcome(ref, outcome)
        except ProviderError:
            raise NotFound()
        payment = Payment.unscoped.filter(provider="simulated", provider_ref=ref).first()
        if payment:
            services.settle_payment(payment.pk, source="simulate")
        return Response({"success": True})
