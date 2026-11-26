"""In-app notifications: a persistent feed per user (the bell in the app), created where things happen.

`notify_*` helpers never raise: a problem here must not break an order, a payment or a reservation.
The browser shows new items within seconds (polling plus the live channel) and plays a sound for the kinds listed in SOUND_KINDS.
"""
import logging

from django.db.models import Q

from .models import Notification

log = logging.getLogger(__name__)

# Staff who should hear about activity at a branch.
FRONT_OF_HOUSE = ("restaurant_admin", "manager", "cashier", "waiter", "waitress")
KITCHEN_TEAM = ("restaurant_admin", "manager", "kitchen")
DELIVERY_TEAM = ("restaurant_admin", "manager", "delivery")


def notify_users(users, kind, title, body="", link="", restaurant=None, about=None):
    """`about` is an optional (object_type, object_id) pair so the detail page can show the full record."""
    try:
        kind_of, pk = about or ("", None)
        rows = [Notification(user=u, restaurant=restaurant, kind=kind, title=title[:160], body=body[:300], link=link[:200], object_type=kind_of, object_id=pk) for u in users]
        if rows:
            Notification.objects.bulk_create(rows)
    except Exception:  # noqa: BLE001
        log.exception("could not create notifications")


def staff_at(restaurant, branch_id, roles):
    """Users with one of `roles` at this branch (restaurant administrators belong to every branch)."""
    from apps.accounts.models import User

    q = Q(memberships__restaurant=restaurant, memberships__is_active=True, memberships__role__in=roles)
    q &= Q(memberships__role="restaurant_admin") | Q(memberships__branches=branch_id)
    return User.objects.filter(q, is_active=True).distinct()


def notify_staff(restaurant, branch_id, roles, kind, title, body="", link="", about=None):
    notify_users(staff_at(restaurant, branch_id, roles), kind, title, body, link, restaurant, about)


def order_created(order):
    link, ref = "/manage/orders", ("order", order.pk)
    where = f" ({order.table_label})" if order.table_label else ""
    notify_staff(order.restaurant, order.branch_id, FRONT_OF_HOUSE, "order_new", f"New order {order.number}", f"{order.get_fulfilment_display()}{where} · {order.currency} {order.total}", link, about=ref)
    if order.status != "awaiting_payment":
        notify_staff(order.restaurant, order.branch_id, ("kitchen",), "order_new", f"New order {order.number}", "", "/manage/kitchen", about=ref)


def order_moved(order, to):
    """Tell the right people when an order changes state (the customer, the kitchen, whoever serves or delivers it)."""
    num, r = order.number, order.restaurant
    customer = [order.customer] if order.customer_id else []
    ref = ("order", order.pk)
    if to == "received":
        notify_staff(r, order.branch_id, KITCHEN_TEAM, "order_new", f"Order {num} sent to the kitchen", "", "/manage/kitchen", about=ref)
    elif to == "preparing":
        notify_users(customer, "order_update", f"Order {num} is being prepared", "", f"/account/orders/{order.pk}", r, about=ref)
    elif to == "ready_for_pickup":
        notify_users(customer, "order_ready", f"Order {num} is ready for pickup", "Come and collect it at the counter.", f"/account/orders/{order.pk}", r, about=ref)
        notify_staff(r, order.branch_id, FRONT_OF_HOUSE, "order_ready", f"Order {num} is ready", order.table_label or order.get_fulfilment_display(), "/manage/orders", about=ref)
    elif to == "out_for_delivery":
        notify_users(customer, "order_update", f"Order {num} is on its way", "", f"/account/orders/{order.pk}", r, about=ref)
        notify_staff(r, order.branch_id, DELIVERY_TEAM, "order_ready", f"Order {num} is ready for delivery", "", "/manage/orders", about=ref)
    elif to == "completed":
        notify_users(customer, "order_update", f"Order {num} is complete", "Thank you!", f"/account/orders/{order.pk}", r, about=ref)
    elif to == "cancelled":
        notify_users(customer, "order_update", f"Order {num} was cancelled", order.cancellation_reason or "", f"/account/orders/{order.pk}", r, about=ref)
        notify_staff(r, order.branch_id, FRONT_OF_HOUSE, "order_update", f"Order {num} was cancelled", order.cancellation_reason or "", "/manage/orders", about=ref)


def payment_received(order, amount):
    notify_staff(order.restaurant, order.branch_id, ("restaurant_admin", "manager", "cashier"), "payment", f"Payment received for {order.number}", f"{order.currency} {amount}", "/manage/orders", about=("order", order.pk))
    if order.customer_id:
        notify_users([order.customer], "payment", f"Payment received for order {order.number}", f"{order.currency} {amount}", f"/account/orders/{order.pk}", order.restaurant, about=("order", order.pk))
