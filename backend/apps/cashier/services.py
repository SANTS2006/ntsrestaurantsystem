"""Cashier shift and till logic. Expected cash is always recomputed on the server from recorded transactions."""
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import serializers

from apps.core.models import audit
from apps.orders.models import Order
from apps.payments.models import Payment, Refund
from apps.tenants.models import Branch

from .models import Shift, ShiftAdjustment

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def _sum(qs, field="amount"):
    return (qs.aggregate(t=Sum(field))["t"] or ZERO).quantize(CENT)


def shift_totals(shift: Shift) -> dict:
    cash = Payment.unscoped.filter(shift=shift, method="cash", status="succeeded")
    refunds = Refund.unscoped.filter(shift=shift, status="succeeded")
    adj = ShiftAdjustment.unscoped.filter(shift=shift, status="approved")
    cash_sales, cash_refunds = _sum(cash), _sum(refunds)
    cash_in, cash_out = _sum(adj.filter(kind="cash_in")), _sum(adj.filter(kind="cash_out"))
    end = shift.closed_at or timezone.now()
    mobile = Payment.unscoped.filter(restaurant=shift.restaurant, branch=shift.branch, method="mobile_money", status="succeeded",
                                     order__cashier=shift.cashier, paid_at__gte=shift.opened_at, paid_at__lte=end)
    return {
        "opening_cash": shift.opening_cash, "cash_sales": cash_sales, "cash_refunds": cash_refunds, "cash_in": cash_in, "cash_out": cash_out,
        "expected_cash": (shift.opening_cash + cash_sales - cash_refunds + cash_in - cash_out).quantize(CENT),
        "cash_transactions": cash.count(), "mobile_money_sales": _sum(mobile), "mobile_money_transactions": mobile.count(),
    }


def open_shift(request, opening_cash, branch_id, branch_ids):
    allowed = Branch.unscoped.filter(restaurant=request.tenant, status="active", pk__in=branch_ids)
    if branch_id is None:
        only = list(allowed[:2])
        if len(only) != 1:
            raise serializers.ValidationError({"branch_id": "Choose the branch you are working at."})
        branch = only[0]
    else:
        branch = allowed.filter(pk=branch_id).first()
        if branch is None:
            raise serializers.ValidationError({"branch_id": "You cannot open a shift at this branch."})
    try:
        with transaction.atomic():
            shift = Shift.objects.create(restaurant=request.tenant, branch=branch, cashier=request.user, opening_cash=opening_cash)
    except IntegrityError:
        raise serializers.ValidationError({"detail": "You already have an open shift. Close it first."})
    audit("shift.opened", actor=request.user, restaurant=request.tenant, obj=shift, metadata={"opening_cash": str(opening_cash)}, request=request)
    return shift


@transaction.atomic
def close_shift(request, shift_id, actual_cash, notes):
    shift = Shift.unscoped.select_for_update().filter(pk=shift_id, restaurant=request.tenant, cashier=request.user).first()
    if shift is None:
        raise serializers.ValidationError({"detail": "Shift not found."})
    if shift.status != Shift.Status.OPEN:
        raise serializers.ValidationError({"detail": "This shift is already closed."})
    if ShiftAdjustment.unscoped.filter(shift=shift, status="pending").exists():
        raise serializers.ValidationError({"detail": "Resolve pending cash adjustments (ask a manager to approve or reject them) before closing."})
    totals = shift_totals(shift)
    actual = Decimal(actual_cash).quantize(CENT)
    variance = (actual - totals["expected_cash"]).quantize(CENT)
    if variance != 0 and not notes.strip():
        raise serializers.ValidationError({"notes": "Explain the difference between expected and counted cash."})
    shift.status, shift.closed_at = Shift.Status.CLOSED, timezone.now()
    shift.expected_cash, shift.actual_cash, shift.variance, shift.close_notes = totals["expected_cash"], actual, variance, notes[:300]
    Shift.unscoped.filter(pk=shift.pk).update(status=shift.status, closed_at=shift.closed_at, expected_cash=shift.expected_cash,
                                              actual_cash=actual, variance=variance, close_notes=shift.close_notes)
    audit("shift.closed", actor=request.user, restaurant=request.tenant, obj=shift,
          metadata={"expected": str(totals["expected_cash"]), "actual": str(actual), "variance": str(variance)}, request=request)
    return Shift.unscoped.get(pk=shift.pk)


@transaction.atomic
def request_adjustment(request, shift_id, kind, amount, reason):
    shift = Shift.unscoped.select_for_update().filter(pk=shift_id, restaurant=request.tenant, cashier=request.user).first()
    if shift is None or shift.status != Shift.Status.OPEN:
        raise serializers.ValidationError({"detail": "Open shift not found."})
    adj = ShiftAdjustment.objects.create(restaurant=request.tenant, branch=shift.branch, shift=shift, kind=kind, amount=amount,
                                         reason=reason, requested_by=request.user)
    audit("shift.adjustment_requested", actor=request.user, restaurant=request.tenant, obj=adj,
          metadata={"kind": kind, "amount": str(amount)}, request=request)
    return adj


@transaction.atomic
def decide_adjustment(request, adjustment_id, approve, note, branch_ids):
    adj = (ShiftAdjustment.unscoped.select_for_update().select_related("shift")
           .filter(pk=adjustment_id, restaurant=request.tenant, branch_id__in=branch_ids).first())
    if adj is None:
        raise serializers.ValidationError({"detail": "Adjustment not found."})
    if adj.status != ShiftAdjustment.Status.PENDING:
        raise serializers.ValidationError({"detail": "This adjustment was already decided."})
    if adj.requested_by_id == request.user.pk:
        raise serializers.ValidationError({"detail": "You cannot approve your own adjustment."})  # independent authorisation
    if adj.shift.status != Shift.Status.OPEN:
        raise serializers.ValidationError({"detail": "The shift is closed."})
    adj.status = ShiftAdjustment.Status.APPROVED if approve else ShiftAdjustment.Status.REJECTED
    adj.decided_by, adj.decided_at, adj.decision_note = request.user, timezone.now(), note[:300]
    adj.save()
    audit("shift.adjustment_approved" if approve else "shift.adjustment_rejected", actor=request.user, restaurant=request.tenant, obj=adj,
          metadata={"amount": str(adj.amount), "kind": adj.kind}, request=request)
    return adj


def dashboard_for(user, tenant):
    """Personal figures only: payments this user recorded, plus online payments on orders this user entered."""
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(tenant.get_settings().timezone)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    now = timezone.now().astimezone(tz)  # "today" is the restaurant's today
    start_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    periods = {"today": start_day, "week": start_day - timedelta(days=6), "month": start_day.replace(day=1)}
    mine = (Payment.unscoped.filter(restaurant=tenant, status="succeeded")
            .filter(Q(recorded_by=user) | Q(order__cashier=user)))
    out = {}
    for name, since in periods.items():
        qs = mine.filter(paid_at__gte=since)
        orders = Order.unscoped.filter(restaurant=tenant, created_at__gte=since).filter(Q(cashier=user) | Q(payments__recorded_by=user)).distinct()
        out[name] = {"total": str(_sum(qs)), "cash": str(_sum(qs.filter(method="cash"))), "mobile_money": str(_sum(qs.filter(method="mobile_money"))),
                     "transactions": qs.count(), "orders_processed": orders.count()}
    return out, mine.select_related("order", "branch").order_by("-paid_at")[:10]
