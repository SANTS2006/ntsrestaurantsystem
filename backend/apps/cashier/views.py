from decimal import Decimal

from django.db.models import Q
from rest_framework import mixins, serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsCashierOrAbove, IsManagerOrAbove, accessible_branch_ids, effective_role
from apps.core.idempotency import run_idempotent
from apps.orders.models import Fulfilment, Order
from apps.accounts.models import Role
from apps.orders.pricing import DiscountInput, LineInput, price_cart
from apps.orders.serializers import OrderDetailSerializer
from apps.orders.services import create_order
from apps.payments import services as pay
from apps.payments.models import Payment
from apps.payments.views import payment_json

from . import services
from .models import Shift, ShiftAdjustment

MONEY = dict(max_digits=12, decimal_places=2, min_value=Decimal("0.00"))


def shift_json(s, with_totals=True):
    d = {"id": s.pk, "status": s.status, "branch_id": s.branch_id, "branch_name": s.branch.name, "cashier_id": s.cashier_id,
         "cashier": s.cashier.full_name or s.cashier.email, "opened_at": s.opened_at, "closed_at": s.closed_at,
         "opening_cash": str(s.opening_cash), "close_notes": s.close_notes}
    if s.status == Shift.Status.CLOSED:  # frozen figures
        d.update(expected_cash=str(s.expected_cash), actual_cash=str(s.actual_cash), variance=str(s.variance))
    if with_totals:
        t = services.shift_totals(s)
        d["totals"] = {k: str(v) for k, v in t.items()}
        if s.status == Shift.Status.OPEN:
            d["expected_cash"] = str(t["expected_cash"])
    return d


def adjustment_json(a):
    return {"id": a.pk, "shift_id": a.shift_id, "kind": a.kind, "amount": str(a.amount), "reason": a.reason, "status": a.status,
            "requested_by": a.requested_by.full_name or a.requested_by.email, "decided_by": (a.decided_by.full_name or a.decided_by.email) if a.decided_by else None,
            "decision_note": a.decision_note, "created_at": a.created_at}


def _my_shift(request):
    return Shift.unscoped.select_related("branch", "cashier").filter(restaurant=request.tenant, cashier=request.user, status="open").first()


class CurrentShiftView(APIView):
    permission_classes = [IsCashierOrAbove]

    def get(self, request):
        s = _my_shift(request)
        return Response({"shift": shift_json(s) if s else None,
                         "adjustments": [adjustment_json(a) for a in s.adjustments.select_related("requested_by", "decided_by")] if s else []})


class OpenShiftSerializer(serializers.Serializer):
    opening_cash = serializers.DecimalField(**MONEY)
    branch_id = serializers.IntegerField(required=False, allow_null=True, default=None)


class OpenShiftView(APIView):
    permission_classes = [IsCashierOrAbove]

    def post(self, request):
        s = OpenShiftSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        shift = services.open_shift(request, s.validated_data["opening_cash"], s.validated_data["branch_id"], accessible_branch_ids(request))
        return Response(shift_json(Shift.unscoped.select_related("branch", "cashier").get(pk=shift.pk)), status=201)


class CloseShiftSerializer(serializers.Serializer):
    actual_cash = serializers.DecimalField(**MONEY)
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class CloseShiftView(APIView):
    permission_classes = [IsCashierOrAbove]

    def post(self, request, pk):
        s = CloseShiftSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        shift = services.close_shift(request, pk, s.validated_data["actual_cash"], s.validated_data["notes"])
        return Response(shift_json(Shift.unscoped.select_related("branch", "cashier").get(pk=shift.pk)))


class AdjustmentSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=ShiftAdjustment.Kind.values)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    reason = serializers.CharField(min_length=3, max_length=300)


class RequestAdjustmentView(APIView):
    permission_classes = [IsCashierOrAbove]

    def post(self, request, pk):
        s = AdjustmentSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        a = services.request_adjustment(request, pk, **s.validated_data)
        return Response(adjustment_json(ShiftAdjustment.unscoped.select_related("requested_by", "decided_by").get(pk=a.pk)), status=201)


class DecideSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class DecideAdjustmentView(APIView):
    permission_classes = [IsManagerOrAbove]

    def post(self, request, pk):
        s = DecideSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        a = services.decide_adjustment(request, pk, s.validated_data["approve"], s.validated_data["note"], accessible_branch_ids(request))
        return Response(adjustment_json(ShiftAdjustment.unscoped.select_related("requested_by", "decided_by").get(pk=a.pk)))


class ShiftViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Cashiers see only their own shifts. Managers/admins see the shifts of their branches."""

    permission_classes = [IsCashierOrAbove]

    def get_queryset(self):
        qs = Shift.unscoped.filter(restaurant=self.request.tenant).select_related("branch", "cashier")
        if effective_role(self.request) == "cashier":
            return qs.filter(cashier=self.request.user)
        qs = qs.filter(branch_id__in=accessible_branch_ids(self.request))
        if self.request.query_params.get("mine") == "1":
            qs = qs.filter(cashier=self.request.user)
        if self.request.query_params.get("status") in ("open", "closed"):
            qs = qs.filter(status=self.request.query_params["status"])
        return qs

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response([shift_json(s) for s in page])

    def retrieve(self, request, *args, **kwargs):
        s = self.get_object()
        d = shift_json(s)
        d["payments"] = [{"reference": p.reference, "order_number": p.order.number, "method": p.method, "amount": str(p.amount),
                          "received": str(p.amount_received) if p.amount_received is not None else None, "change": str(p.change_given), "paid_at": p.paid_at}
                         for p in Payment.unscoped.filter(shift=s).select_related("order").order_by("paid_at")]
        d["refunds"] = [{"reference": r.reference, "amount": str(r.amount), "reason": r.reason} for r in s.refunds.all()]
        d["adjustments"] = [adjustment_json(a) for a in s.adjustments.select_related("requested_by", "decided_by")]
        return Response(d)


class PendingAdjustmentsView(APIView):
    permission_classes = [IsManagerOrAbove]

    def get(self, request):
        qs = (ShiftAdjustment.unscoped.filter(restaurant=request.tenant, status="pending", branch_id__in=accessible_branch_ids(request))
              .select_related("requested_by", "decided_by"))
        return Response([adjustment_json(a) for a in qs])


# ---- personal dashboard --------------------------------------------------------------------------
class DashboardView(APIView):
    permission_classes = [IsCashierOrAbove]

    def get(self, request):
        periods, recent = services.dashboard_for(request.user, request.tenant)
        orders = (Order.unscoped.filter(restaurant=request.tenant).filter(Q(cashier=request.user) | Q(payments__recorded_by=request.user))
                  .distinct().select_related("branch").prefetch_related("items")[:10])
        from apps.orders.serializers import OrderListSerializer
        s = _my_shift(request)
        return Response({"periods": periods, "shift": shift_json(s) if s else None,
                         "recent_orders": OrderListSerializer(orders, many=True, context={"request": request}).data,
                         "recent_transactions": [{"reference": p.reference, "order_number": p.order.number, "method": p.method, "amount": str(p.amount),
                                                  "paid_at": p.paid_at, "branch": p.branch.name} for p in recent]})


def apply_payment_choice(request, order, choice, amount_received, payer_phone, branches):
    """Take payment for a freshly created staff-entered order: cash now, mobile money via the provider, or pay later."""
    payment, change = None, None
    if choice == "cash":
        payment = pay.record_cash_payment(request, order.pk, amount_received, branches)
        change = str(payment.change_given)
    elif choice == "mobile_money":
        locked = Order.unscoped.select_for_update(of=("self",)).select_related("restaurant", "branch").get(pk=order.pk)
        payment = pay.start_provider_payment(request, locked, payer_phone)
    return payment, change


# ---- in-person order --------------------------------------------------------------------------------
class CashierOrderSerializer(serializers.Serializer):
    items = LineInput(many=True)
    fulfilment = serializers.ChoiceField(choices=[Fulfilment.PICKUP, Fulfilment.DINE_IN, Fulfilment.DELIVERY], default=Fulfilment.DINE_IN)
    branch_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    contact_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="Walk-in customer")
    contact_phone = serializers.RegexField(r"^[0-9+()\-\s]{6,30}$", required=False, allow_blank=True, default="", error_messages={"invalid": "Enter a valid phone number."})
    contact_email = serializers.EmailField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    address = serializers.DictField(child=serializers.CharField(allow_blank=True, max_length=250), required=False, default=dict)
    payment = serializers.ChoiceField(choices=["cash", "mobile_money", "pay_later"])
    amount_received = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), required=False, allow_null=True, default=None)
    payer_phone = serializers.RegexField(r"^[0-9+()\-\s]{6,30}$", required=False, allow_blank=True, default="")
    discount = DiscountInput(required=False, allow_null=True, default=None)

    def validate(self, a):
        if a["fulfilment"] == "delivery" and (not a["contact_phone"] or not (a["address"].get("line1") and a["address"].get("city"))):
            raise serializers.ValidationError({"address": "Delivery needs a phone number and an address."})
        if a["payment"] == "cash" and a["amount_received"] is None:
            raise serializers.ValidationError({"amount_received": "Enter the cash received."})
        if a["payment"] == "mobile_money" and not (a["payer_phone"] or a["contact_phone"]):
            raise serializers.ValidationError({"payer_phone": "Enter the customer's mobile money number."})
        return a


class CashierOrderView(APIView):
    """A cashier/manager enters an order for a guest. No customer account is created or exposed."""

    permission_classes = [IsCashierOrAbove]

    def post(self, request):
        s = CashierOrderSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        d["items"] = [dict(i, addons=[dict(a) for a in i["addons"]]) for i in d["items"]]
        branches, role = accessible_branch_ids(request), effective_role(request)
        shift = _my_shift(request)
        branch_id = d["branch_id"] or (shift.branch_id if shift else (next(iter(branches)) if len(branches) == 1 else None))
        if branch_id is None or branch_id not in branches:
            raise serializers.ValidationError({"branch_id": "Choose a branch you work at."})
        d.update(max_discount_percent=_max_discount(request, role), branch_id=branch_id, payment_method="cash" if d["payment"] != "mobile_money" else "mobile_money",
                 address_snapshot=d["address"] if d["fulfilment"] == "delivery" else {})

        def handler():
            order = create_order(request, d, customer=None, source="cashier", cashier=request.user, role=role)
            payment, change = apply_payment_choice(request, order, d["payment"], d["amount_received"], d["payer_phone"] or d["contact_phone"], branches)
            order = Order.unscoped.prefetch_related("items", "history", "payments__receipt").select_related("branch").get(pk=order.pk)
            body = {"order": dict(OrderDetailSerializer(order, context={"request": request}).data)}
            if payment is not None:
                pj = payment_json(payment)
                pj["receipt_id"] = payment.receipt.pk if hasattr(payment, "receipt") else None
                body.update(payment=pj, change_given=change)
            return 201, body

        status, body = run_idempotent(request, "cashier.order", request.headers.get("Idempotency-Key", ""), request.data, handler)
        return Response(body, status=status)


def _max_discount(request, role):
    """Cashiers are capped by the restaurant setting; managers and administrators are not."""
    return request.tenant.get_settings().cashier_max_discount_percent if role == Role.CASHIER else None


class CashierQuoteView(APIView):
    """Staff cart pricing with an optional, permission-checked discount (the public quote endpoint never accepts one)."""

    permission_classes = [IsCashierOrAbove]

    def post(self, request):
        class QuoteIn(serializers.Serializer):
            items = LineInput(many=True)
            fulfilment = serializers.ChoiceField(choices=[Fulfilment.PICKUP, Fulfilment.DINE_IN, Fulfilment.DELIVERY], default=Fulfilment.DINE_IN)
            discount = DiscountInput(required=False, allow_null=True, default=None)

        s = QuoteIn(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        items = [dict(i, addons=[dict(a) for a in i["addons"]]) for i in d["items"]]
        fulfil = "pickup" if d["fulfilment"] == Fulfilment.DINE_IN else d["fulfilment"]
        quote = price_cart(request.tenant, items, fulfil, discount=d["discount"], max_discount_percent=_max_discount(request, effective_role(request)))
        return Response(quote.as_dict())
