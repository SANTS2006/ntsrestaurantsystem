"""Order creation and the status state machine. All money and stock effects happen inside one
database transaction with row locks; nothing here trusts client-supplied amounts."""
from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from apps.accounts.models import Role
from apps.catalog.models import Product, StockMovement
from apps.core.models import audit
from apps.notifications.services import queue_email
from apps.tenants.models import Branch

from .models import (Fulfilment, Order, OrderItem, OrderSequence, OrderStatusHistory, PaymentMethod,
                     PaymentStatus, Status)
from .pricing import price_cart

S = Status

# Every legal move. Anything not listed is rejected, regardless of who asks.
TRANSITIONS = {
    S.AWAITING_PAYMENT: {S.PAYMENT_PROCESSING, S.CONFIRMED, S.CANCELLED},
    S.PAYMENT_PROCESSING: {S.CONFIRMED, S.AWAITING_PAYMENT, S.CANCELLED},
    S.CONFIRMED: {S.RECEIVED, S.CANCELLED},
    S.RECEIVED: {S.PREPARING, S.CANCELLED},
    S.PREPARING: {S.READY_FOR_PICKUP, S.OUT_FOR_DELIVERY, S.CANCELLED},
    S.READY_FOR_PICKUP: {S.COMPLETED},
    S.OUT_FOR_DELIVERY: {S.COMPLETED},
    S.COMPLETED: {S.REFUND_PENDING},
    S.CANCELLED: {S.REFUND_PENDING},
    S.REFUND_PENDING: {S.REFUNDED},
    S.REFUNDED: set(),
}
# Driven by the payment module (Phase 6), never by a manual status change.
SYSTEM_ONLY = {S.PAYMENT_PROCESSING, S.REFUND_PENDING, S.REFUNDED}

_R = Role
STAFF_MOVES = {
    _R.CASHIER: {(S.AWAITING_PAYMENT, S.CONFIRMED), (S.CONFIRMED, S.RECEIVED), (S.READY_FOR_PICKUP, S.COMPLETED),
                 (S.AWAITING_PAYMENT, S.CANCELLED), (S.CONFIRMED, S.CANCELLED), (S.RECEIVED, S.CANCELLED)},
    _R.KITCHEN: {(S.RECEIVED, S.PREPARING), (S.PREPARING, S.READY_FOR_PICKUP), (S.PREPARING, S.OUT_FOR_DELIVERY)},
    _R.WAITER: {(S.READY_FOR_PICKUP, S.COMPLETED)},
    _R.WAITRESS: {(S.READY_FOR_PICKUP, S.COMPLETED)},
    _R.DELIVERY: {(S.OUT_FOR_DELIVERY, S.COMPLETED)},
}


def label(status):
    return Status(status).label


def valid_target(order, to) -> bool:
    if to not in TRANSITIONS.get(order.status, set()) or to in SYSTEM_ONLY:
        return False
    if to == S.READY_FOR_PICKUP and order.fulfilment == Fulfilment.DELIVERY:
        return False
    if to == S.OUT_FOR_DELIVERY and order.fulfilment != Fulfilment.DELIVERY:
        return False
    return True


def allowed_targets(order, role):
    """Statuses this staff role may move the order to right now."""
    out = []
    for to in TRANSITIONS.get(order.status, set()):
        if not valid_target(order, to):
            continue
        if role in (_R.PLATFORM_ADMIN, _R.RESTAURANT_ADMIN, _R.MANAGER) or (order.status, to) in STAFF_MOVES.get(role, set()):
            out.append(to)
    return sorted(out)


def _next_number(restaurant):
    seq, _ = OrderSequence.objects.select_for_update().get_or_create(restaurant=restaurant)
    seq.last_number += 1
    seq.save(update_fields=["last_number"])
    return f"ORD-{seq.last_number:06d}"


def _tracking_url(restaurant, order):
    return f"{restaurant.public_url}/account/orders/{order.pk}"


def _wants_order_emails(order, restaurant):
    if order.customer_id is None:
        return bool(order.contact_email)
    m = order.customer.memberships.filter(restaurant=restaurant).first()
    return bool(order.contact_email) and (m is None or {"order_emails": True, **(m.preferences or {})}["order_emails"])


def _resolve_branch(restaurant, branch_id):
    branches = Branch.unscoped.filter(restaurant=restaurant, status="active")
    if branch_id is not None:
        branch = branches.filter(pk=branch_id).first()
        if branch is None:
            raise serializers.ValidationError({"branch_id": "Choose a valid branch."})
        return branch
    only = list(branches[:2])
    if len(only) == 1:
        return only[0]
    raise serializers.ValidationError({"branch_id": "Choose the branch to order from."})


@transaction.atomic
def create_order(request, data, *, customer=None, source="online", cashier=None, role=Role.CUSTOMER, table=None):
    """Create an order (online customer, or staff-entered for a guest). Runs inside ``run_idempotent`` so a retry
    can never create a second one. ``customer`` is None for guest/in-person orders."""
    restaurant, user = request.tenant, request.user
    if data["payment_method"] == PaymentMethod.MOBILE_MONEY:
        from apps.payments.providers import online_payments_available

        if not (restaurant.get_settings().online_payments_enabled and online_payments_available()):
            raise serializers.ValidationError({"payment_method": "Online payment is not available. Choose cash on pickup or delivery."})
    branch = _resolve_branch(restaurant, data.get("branch_id"))
    address = {}
    if data["fulfilment"] == Fulfilment.DELIVERY:
        address = data.get("address_snapshot") or {}
        if not address.get("line1") or not address.get("city"):
            raise serializers.ValidationError({"address": "A delivery address is required."})

    quote = price_cart(restaurant, data["items"], data["fulfilment"], lock=True, discount=data.get("discount"), max_discount_percent=data.get("max_discount_percent"))
    order = Order.objects.create(
        restaurant=restaurant, branch=branch, customer=customer, cashier=cashier, number=_next_number(restaurant), source=source, table=table, table_label=table.label if table else "",
        fulfilment=data["fulfilment"], payment_method=data["payment_method"], payment_status=PaymentStatus.UNPAID,
        contact_name=data["contact_name"] or (customer.full_name if customer else ""), contact_phone=data["contact_phone"],
        contact_email=(customer.email if customer else data.get("contact_email", "")),
        delivery_address=address, customer_notes=data.get("notes", ""), currency=quote.currency,
        tax_rate_percent=quote.tax_rate_percent, subtotal=quote.subtotal, discount_total=quote.discount_total,
        tax_total=quote.tax_total, delivery_fee=quote.delivery_fee, total=quote.total,
        discount_reason=(data.get("discount") or {}).get("reason", ""), discount_by=user if data.get("discount") else None)

    sold: dict[int, tuple[Product, int]] = {}
    for line in quote.lines:
        OrderItem.objects.create(
            restaurant=restaurant, order=order, product=line.product, product_name=line.product.name,
            variation_name=line.variation.name if line.variation else "", unit_price=line.unit_price,
            quantity=line.quantity, line_total=line.line_total, addons=line.addons, instructions=line.instructions)
        if line.product.track_inventory:
            p, q = sold.get(line.product.pk, (line.product, 0))
            sold[line.product.pk] = (p, q + line.quantity)
    from apps.procurement.services import apply_recipe_usage

    apply_recipe_usage(order, user)  # ingredient stock for products that have a recipe; never blocks a sale
    for p, qty in sold.values():  # rows are already locked by price_cart(lock=True)
        p.stock_quantity -= qty
        p.save()
        StockMovement.objects.create(restaurant=restaurant, product=p, delta=-qty, quantity_after=p.stock_quantity,
                                     reason=StockMovement.Reason.SALE, note=order.number, actor=user)

    OrderStatusHistory.objects.create(restaurant=restaurant, order=order, from_status="", to_status=order.status,
                                      actor=user, actor_role=role, note="Order placed")
    audit("order.created", actor=user, restaurant=restaurant, obj=order,
          metadata={"number": order.number, "total": str(order.total), "items": len(quote.lines)}, request=request)
    if quote.discount_total:
        audit("order.discount_applied", actor=user, restaurant=restaurant, obj=order,
              metadata={"number": order.number, "discount": str(quote.discount_total), "reason": order.discount_reason[:200]}, request=request)
    if order.contact_email:
        queue_email("order_confirmation", order.contact_email, {
            "name": order.contact_name, "number": order.number, "total": f"{order.currency} {order.total}",
            "fulfilment": order.get_fulfilment_display(), "payment": order.get_payment_method_display(),
            "items": [f"{i.quantity} × {i.product_name}" + (f" ({i.variation_name})" if i.variation_name else "")
                      for i in order.items.all()], "url": _tracking_url(restaurant, order)},
            restaurant=restaurant, dedupe_key=f"order:{order.pk}:created")
    from apps.notifications import inapp

    inapp.order_created(order)
    return order


def _restore_stock(order, actor):
    if not order.stock_restored:
        from apps.procurement.services import apply_recipe_usage

        apply_recipe_usage(order, actor, restore=True)
    if order.stock_restored:
        return
    for item in order.items.select_related("product"):
        p = item.product
        if p is None or not p.track_inventory:
            continue
        p = Product.unscoped.select_for_update().get(pk=p.pk)
        p.stock_quantity += item.quantity
        p.save()
        StockMovement.objects.create(restaurant=order.restaurant, product=p, delta=item.quantity, quantity_after=p.stock_quantity,
                                     reason=StockMovement.Reason.RETURN, note=f"{order.number} cancelled", actor=actor)
    order.stock_restored = True


@transaction.atomic
def transition_order(request, order_id, to, *, role, note="", customer_cancel=False):
    """Move an order through the state machine, under a row lock, recording who did it and why."""
    restaurant, actor = request.tenant, request.user
    order = Order.unscoped.select_for_update(of=("self",)).select_related("customer", "restaurant").get(pk=order_id, restaurant=restaurant)
    if not customer_cancel and to not in allowed_targets(order, role):
        raise serializers.ValidationError({"status": f"You cannot move this order from “{label(order.status)}” to “{label(to)}”."})
    if to == S.CANCELLED:
        if not note.strip():
            raise serializers.ValidationError({"note": "Please give a reason for cancelling."})
        if order.amount_paid > Decimal("0"):
            raise serializers.ValidationError({"status": "A paid order must be refunded before it can be cancelled."})
        _restore_stock(order, actor)
        order.cancellation_requested = False
        order.cancellation_reason = note[:300]
    previous = order.status
    order.status = to
    order.save()
    OrderStatusHistory.objects.create(restaurant=restaurant, order=order, from_status=previous, to_status=to,
                                      actor=actor, actor_role=role, note=note[:300])
    audit("order.status_changed", actor=actor, restaurant=restaurant, obj=order,
          metadata={"from": previous, "to": to, "role": str(role)}, request=request)
    if _wants_order_emails(order, restaurant):
        queue_email("order_status", order.contact_email, {
            "name": order.contact_name, "number": order.number, "status": label(to), "note": note,
            "url": _tracking_url(restaurant, order)}, restaurant=restaurant, dedupe_key=f"order:{order.pk}:status:{to}")
    from apps.notifications import inapp

    inapp.order_moved(order, to)
    return order


def system_transition(order, to, *, note="", actor=None, role="system"):
    """Payment-driven status change. The caller must hold a row lock on ``order``. Still bound by TRANSITIONS."""
    if to not in TRANSITIONS.get(order.status, set()):
        return False
    previous = order.status
    order.status = to
    order.save()
    OrderStatusHistory.objects.create(restaurant=order.restaurant, order=order, from_status=previous, to_status=to,
                                      actor=actor, actor_role=str(role), note=note[:300])
    audit("order.status_changed", actor=actor, restaurant=order.restaurant, obj=order,
          metadata={"from": previous, "to": to, "role": str(role)})
    if _wants_order_emails(order, order.restaurant):
        queue_email("order_status", order.contact_email, {
            "name": order.contact_name, "number": order.number, "status": label(to), "note": note,
            "url": _tracking_url(order.restaurant, order)}, restaurant=order.restaurant, dedupe_key=f"order:{order.pk}:status:{to}")
    from apps.notifications import inapp

    inapp.order_moved(order, to)
    return True


@transaction.atomic
def customer_cancel(request, order_id, reason):
    """Customers cancel directly before the restaurant accepts; afterwards they can only request it."""
    order = Order.unscoped.select_for_update().get(pk=order_id, restaurant=request.tenant, customer=request.user)
    if order.status == S.AWAITING_PAYMENT:
        return transition_order(request, order_id, S.CANCELLED, role=Role.CUSTOMER, note=reason or "Cancelled by customer",
                                customer_cancel=True), "cancelled"
    if order.status in (S.CONFIRMED, S.RECEIVED):
        order.cancellation_requested = True
        order.cancellation_reason = (reason or "Customer asked to cancel")[:300]
        order.save(update_fields=["cancellation_requested", "cancellation_reason", "updated_at"])
        OrderStatusHistory.objects.create(restaurant=order.restaurant, order=order, from_status=order.status, to_status=order.status,
                                          actor=request.user, actor_role=Role.CUSTOMER, note=f"Cancellation requested: {order.cancellation_reason}")
        audit("order.cancellation_requested", actor=request.user, restaurant=order.restaurant, obj=order, request=request)
        return order, "requested"
    raise serializers.ValidationError({"status": "This order can no longer be cancelled. Please contact the restaurant."})
