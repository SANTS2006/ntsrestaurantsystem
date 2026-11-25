"""Payment business logic. Money state changes only happen here, in transactions with row locks, and only
after the provider's own status endpoint (queried by the server) confirms them. The browser, a redirect or a
webhook body can never mark a payment paid."""
import logging
import uuid
from decimal import Decimal

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.core.models import audit
from apps.notifications.services import queue_email
from apps.orders.models import Order, PaymentStatus, Status
from apps.orders.services import system_transition

from .models import Payment, Receipt, ReceiptSequence, Refund
from .providers import ProviderError, get_provider

log = logging.getLogger(__name__)
CENT = Decimal("0.01")


def _ref(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:18].upper()}"


def refunded_total(payment):
    return sum((r.amount for r in payment.refunds.all() if r.status in ("pending", "succeeded")), Decimal("0.00"))


# ---- receipts ----------------------------------------------------------------------------------
def build_receipt_data(payment, number):
    o, r, b = payment.order, payment.restaurant, payment.branch
    return {
        "number": number, "issued_at": timezone.now().isoformat(),
        "restaurant": {"name": r.name, "logo": r.logo.url if r.logo else "", "phone": r.contact_phone, "email": r.contact_email, "address": r.address},
        "branch": {"name": b.name, "address": b.address, "phone": b.phone},
        "order_number": o.number, "fulfilment": o.fulfilment, "currency": o.currency,
        "customer": {"name": o.contact_name, "phone": o.contact_phone, "email": o.contact_email},
        "cashier": (payment.recorded_by.full_name or payment.recorded_by.email) if payment.recorded_by else "",
        "items": [{"name": i.product_name, "variation": i.variation_name, "quantity": i.quantity, "unit_price": str(i.unit_price),
                   "line_total": str(i.line_total), "addons": i.addons} for i in o.items.all()],
        "totals": {"subtotal": str(o.subtotal), "discount": str(o.discount_total), "tax": str(o.tax_total),
                   "delivery_fee": str(o.delivery_fee), "total": str(o.total)},
        "payment": {"method": payment.method, "reference": payment.reference, "provider_ref": payment.provider_ref,
                    "amount": str(payment.amount), "received": str(payment.amount_received) if payment.amount_received is not None else "",
                    "change": str(payment.change_given), "paid_at": payment.paid_at.isoformat() if payment.paid_at else "", "status": payment.status},
    }


def issue_receipt(payment):
    """One receipt per successful payment, numbered per restaurant. Safe to call twice."""
    existing = Receipt.unscoped.filter(payment=payment).first()
    if existing:
        return existing
    seq, _ = ReceiptSequence.objects.select_for_update().get_or_create(restaurant=payment.restaurant)
    seq.last_number += 1
    seq.save(update_fields=["last_number"])
    number = f"RCT-{seq.last_number:06d}"
    receipt = Receipt.objects.create(restaurant=payment.restaurant, branch=payment.branch, payment=payment, order=payment.order,
                                     number=number, data=build_receipt_data(payment, number))
    order = payment.order
    if order.contact_email:
        queue_email("payment_receipt", order.contact_email, {
            "name": order.contact_name, "number": number, "order_number": order.number,
            "amount": f"{order.currency} {payment.amount}", "method": payment.get_method_display(),
            "url": f"{payment.restaurant.public_url}/account/orders/{order.pk}"},
            restaurant=payment.restaurant, dedupe_key=f"receipt:{receipt.pk}")  # a replayed webhook never re-sends it
    return receipt


# ---- marking paid ------------------------------------------------------------------------------
def _apply_success(payment, order):
    payment.status = Payment.Status.SUCCEEDED
    payment.paid_at = timezone.now()
    payment.save()
    order.amount_paid = (order.amount_paid + payment.amount).quantize(CENT)
    order.payment_status = PaymentStatus.PAID if order.amount_paid >= order.total else PaymentStatus.PARTIAL
    order.save()
    if order.status in (Status.PAYMENT_PROCESSING, Status.AWAITING_PAYMENT):
        system_transition(order, Status.CONFIRMED, note="Payment confirmed", actor=payment.recorded_by)
    else:
        # e.g. the order was cancelled while the customer was paying: keep the money visible for a refund
        audit("payment.after_state_change", restaurant=payment.restaurant, obj=payment, metadata={"order_status": order.status})
    audit("payment.succeeded", actor=payment.recorded_by, restaurant=payment.restaurant, obj=payment,
          metadata={"amount": str(payment.amount), "method": payment.method})
    return issue_receipt(payment)


@transaction.atomic
def settle_payment(payment_id, *, source="reconcile"):
    """Ask the provider for the authoritative status of an online payment and apply it exactly once."""
    payment = Payment.unscoped.select_for_update().get(pk=payment_id)
    if payment.status != Payment.Status.PENDING or payment.provider == "cash":
        return payment
    try:
        remote = get_provider(payment.provider).fetch_status(payment.provider_ref)
    except ProviderError as exc:
        log.warning("status check failed for %s: %s", payment.reference, exc)
        return payment  # stays pending; reconciliation retries
    if remote.status == "pending":
        return payment
    order = Order.unscoped.select_for_update().select_related("restaurant", "branch", "customer").get(pk=payment.order_id)
    if remote.status == "failed":
        payment.status = Payment.Status.FAILED
        payment.failure_reason = "Declined or expired at the provider"
        payment.save()
        if order.status == Status.PAYMENT_PROCESSING:
            system_transition(order, Status.AWAITING_PAYMENT, note="Payment failed")
        audit("payment.failed", restaurant=payment.restaurant, obj=payment, metadata={"source": source})
        return payment
    if remote.amount.quantize(CENT) != payment.amount or remote.currency != payment.currency:
        payment.status = Payment.Status.MISMATCH
        payment.failure_reason = f"Provider reported {remote.amount} {remote.currency}"
        payment.save()
        audit("payment.mismatch", restaurant=payment.restaurant, obj=payment,
              metadata={"expected": str(payment.amount), "reported": str(remote.amount), "currency": remote.currency})
        return payment
    _apply_success(payment, order)
    return payment


# ---- initiation --------------------------------------------------------------------------------
def initiate_online_payment(request, order_id, phone):
    """Create (or return the in-flight) payment for the customer's own order and start it with the provider."""
    with transaction.atomic():
        order = (Order.unscoped.select_for_update().select_related("restaurant", "branch")
                 .filter(pk=order_id, restaurant=request.tenant, customer=request.user).first())
        if order is None:
            raise serializers.ValidationError({"order_id": "Order not found."})
        if order.payment_method != "mobile_money":
            raise serializers.ValidationError({"order_id": "This order is not an online-payment order."})
        if order.status not in (Status.AWAITING_PAYMENT, Status.PAYMENT_PROCESSING) or order.payment_status == PaymentStatus.PAID:
            raise serializers.ValidationError({"order_id": "This order cannot be paid right now."})
        return start_provider_payment(request, order, phone)


def start_provider_payment(request, order, phone):
    """Start (or return the in-flight) online payment for a locked order. Used for customers and for staff-entered orders."""
    pending = order.payments.filter(status=Payment.Status.PENDING).exclude(provider="cash").first()
    if pending:
        return pending
    payment = Payment(restaurant=order.restaurant, branch=order.branch, order=order, reference=_ref("PAY"),
                      provider=get_provider().name, method=Payment.Method.MOBILE_MONEY, amount=order.total - order.amount_paid,
                      currency=order.currency, payer_phone=phone, recorded_by=None)
    payment.save()
    try:
        created = get_provider(payment.provider).create_payment(
            reference=payment.reference, amount=payment.amount, currency=payment.currency, phone=phone,
            return_url=f"{order.restaurant.public_url}/account/orders/{order.pk}")
    except ProviderError as exc:
        log.error("payment initiation failed: %s", exc)
        raise serializers.ValidationError({"detail": "The payment service is unavailable. Please try again or pay with cash."})
    payment.provider_ref = created.provider_ref
    payment.save()
    payment.redirect_url = created.redirect_url  # transient, not stored
    system_transition(order, Status.PAYMENT_PROCESSING, note="Payment started")
    audit("payment.initiated", actor=request.user, restaurant=order.restaurant, obj=payment,
          metadata={"amount": str(payment.amount), "provider": payment.provider}, request=request)
    return payment


# ---- cash --------------------------------------------------------------------------------------
@transaction.atomic
def record_cash_payment(request, order_id, amount_received, branch_ids):
    """A cashier/manager records cash taken for an order: change is calculated and a receipt issued."""
    order = (Order.unscoped.select_for_update().select_related("restaurant", "branch")
             .filter(pk=order_id, restaurant=request.tenant, branch_id__in=branch_ids).first())
    if order is None:
        raise serializers.ValidationError({"order_id": "Order not found."})
    if order.status in (Status.CANCELLED, Status.REFUNDED, Status.REFUND_PENDING):
        raise serializers.ValidationError({"order_id": "This order cannot take payment."})
    if order.payments.filter(status=Payment.Status.PENDING).exclude(provider="cash").exists():
        raise serializers.ValidationError({"order_id": "An online payment is in progress for this order."})
    from apps.accounts.permissions import effective_role
    from apps.cashier.models import Shift

    shift = Shift.unscoped.select_for_update().filter(cashier=request.user, status="open", branch=order.branch).first()
    if shift is None and effective_role(request) == "cashier":
        raise serializers.ValidationError({"shift": "Open your shift at this branch before taking cash."})
    due = (order.total - order.amount_paid).quantize(CENT)
    if due <= 0:
        raise serializers.ValidationError({"order_id": "This order is already paid."})
    received = Decimal(amount_received).quantize(CENT)
    if received < due:
        raise serializers.ValidationError({"amount_received": f"Amount received must be at least {due}."})
    payment = Payment(restaurant=order.restaurant, branch=order.branch, order=order, reference=_ref("CSH"), provider="cash",
                      method=Payment.Method.CASH, amount=due, currency=order.currency, amount_received=received,
                      change_given=(received - due).quantize(CENT), recorded_by=request.user, shift=shift)
    payment.save()
    _apply_success(payment, order)
    audit("payment.cash_recorded", actor=request.user, restaurant=order.restaurant, obj=payment,
          metadata={"due": str(due), "received": str(received)}, request=request)
    return payment


# ---- refunds -----------------------------------------------------------------------------------
@transaction.atomic
def refund_payment(request, payment_id, amount, reason, branch_ids, role, manual_reference=""):
    payment = (Payment.unscoped.select_for_update().select_related("order", "restaurant", "branch")
               .filter(pk=payment_id, restaurant=request.tenant, branch_id__in=branch_ids).first())
    if payment is None:
        raise serializers.ValidationError({"payment_id": "Payment not found."})
    if payment.status != Payment.Status.SUCCEEDED:
        raise serializers.ValidationError({"payment_id": "Only a successful payment can be refunded."})
    amount = Decimal(amount).quantize(CENT)
    available = (payment.amount - refunded_total(payment)).quantize(CENT)
    if amount <= 0 or amount > available:
        raise serializers.ValidationError({"amount": f"Refund must be between 0.01 and {available}."})
    refund = Refund(restaurant=payment.restaurant, branch=payment.branch, payment=payment, order=payment.order,
                    reference=_ref("RFD"), amount=amount, reason=reason[:300], approved_by=request.user)
    if payment.provider == "cash" and payment.shift_id and payment.shift.status == "open":
        refund.shift = payment.shift  # cash goes back out of the till that took it (only while that shift is open)
    if payment.provider == "cash":
        refund.status = Refund.Status.SUCCEEDED  # cash handed back across the counter
    elif not get_provider(payment.provider).supports_refunds:
        # The provider has no refund API: the money is returned in its dashboard, and the reference is recorded here (audited).
        if len(manual_reference.strip()) < 3:
            raise serializers.ValidationError({"manual_reference": "This provider has no refund API. Refund the customer in the provider dashboard, then enter that refund reference here to record it."})
        refund.provider_ref = manual_reference.strip()[:100]
        refund.status = Refund.Status.SUCCEEDED
    else:
        try:
            refund.provider_ref = get_provider(payment.provider).refund(
                provider_ref=payment.provider_ref, reference=refund.reference, amount=amount, currency=payment.currency)
            refund.status = Refund.Status.SUCCEEDED
        except ProviderError as exc:
            log.error("refund failed: %s", exc)
            raise serializers.ValidationError({"detail": "The provider could not process the refund. Nothing was changed."})
    refund.save()
    order = Order.unscoped.select_for_update().get(pk=payment.order_id)
    order.amount_paid = max(Decimal("0.00"), order.amount_paid - amount).quantize(CENT)
    fully = refunded_total(payment) >= payment.amount
    if fully and order.amount_paid == 0:
        order.payment_status = PaymentStatus.REFUNDED
    order.save()
    if fully and order.amount_paid == 0 and order.status in (Status.COMPLETED, Status.CANCELLED):
        system_transition(order, Status.REFUND_PENDING, note=reason, actor=request.user, role=role)
        system_transition(order, Status.REFUNDED, note="Refund completed", actor=request.user, role=role)
    audit("payment.refunded", actor=request.user, restaurant=payment.restaurant, obj=payment,
          metadata={"refund": refund.reference, "amount": str(amount), "reason": reason[:200]}, request=request)
    queue_email("refund_notice", order.contact_email, {"name": order.contact_name, "number": order.number,
                "amount": f"{order.currency} {amount}"}, restaurant=payment.restaurant,
                dedupe_key=f"refund:{refund.pk}") if order.contact_email else None
    return refund


# ---- reconciliation ----------------------------------------------------------------------------
def reconcile_pending(older_than_minutes=5):
    """Re-check online payments that are still pending (lost webhook, closed browser...). Safe to run repeatedly."""
    cutoff = timezone.now() - timedelta(minutes=older_than_minutes)
    ids = list(Payment.unscoped.filter(status=Payment.Status.PENDING, created_at__lte=cutoff).exclude(provider="cash")
               .values_list("pk", flat=True))
    return [settle_payment(pk, source="reconcile").status for pk in ids]
