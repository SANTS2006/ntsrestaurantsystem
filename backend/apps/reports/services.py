"""Branch and restaurant reports. Every figure is aggregated in the database from recorded transactions.

Definitions (shown to users in the UI as well):
* booked sales      = value of orders in the period that were not cancelled or refunded
* collected         = successful payments received in the period (by payment date)
* refunds           = successful refunds issued in the period
* net collected     = collected - refunds
* outstanding       = unpaid balance of accepted orders (confirmed through completed) created in the period
"""
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Count, DecimalField, ExpressionWrapper, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.cashier.models import Shift
from apps.catalog.models import Product
from apps.orders.models import Order, OrderItem, OrderStatusHistory, Status
from apps.payments.models import Payment, Refund
from apps.tenants.models import Branch

CENT = Decimal("0.01")
MAX_DAYS = 366
PENDING = [Status.AWAITING_PAYMENT, Status.PAYMENT_PROCESSING, Status.CONFIRMED, Status.RECEIVED, Status.PREPARING,
           Status.READY_FOR_PICKUP, Status.OUT_FOR_DELIVERY]
ACCEPTED = [Status.CONFIRMED, Status.RECEIVED, Status.PREPARING, Status.READY_FOR_PICKUP, Status.OUT_FOR_DELIVERY, Status.COMPLETED]
DEAD = [Status.CANCELLED, Status.REFUNDED]
DEC = DecimalField(max_digits=14, decimal_places=2)


@contextmanager
def tenant_tz(tenant):
    """Run report queries in the restaurant's own time zone: `__date`, TruncDate/Month and ExtractHour all follow the active zone."""
    name = tenant.get_settings().timezone if tenant is not None else "UTC"
    try:
        tz = ZoneInfo(name)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    timezone.activate(tz)
    try:
        yield tz
    finally:
        timezone.deactivate()


class TenantTimezoneMixin:
    """DRF view mixin: activates the restaurant's time zone for the whole request (queries and rendered timestamps)."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        t = getattr(request, "tenant", None)
        if t is not None:
            try:
                timezone.activate(ZoneInfo(t.get_settings().timezone))
            except Exception:  # noqa: BLE001
                pass

    def finalize_response(self, request, response, *args, **kwargs):
        timezone.deactivate()
        return super().finalize_response(request, response, *args, **kwargs)


def m(v):
    return str((v or Decimal("0")).quantize(CENT))


def parse_range(params):
    def one(name, default):
        raw = params.get(name)
        if not raw:
            return default
        try:
            return date.fromisoformat(raw)
        except ValueError:
            raise ValidationError({name: "Use the format YYYY-MM-DD."})

    end = one("to", timezone.localdate())  # the active (restaurant) time zone
    start = one("from", end - timedelta(days=29))
    if start > end:
        raise ValidationError({"from": "The start date must not be after the end date."})
    if (end - start).days >= MAX_DAYS:
        raise ValidationError({"from": f"Choose a range of at most {MAX_DAYS} days."})
    return start, end


def _base_orders(tenant, branch_ids, start, end):
    return Order.unscoped.filter(restaurant=tenant, branch_id__in=branch_ids, created_at__date__gte=start, created_at__date__lte=end)


def _payments(tenant, branch_ids, start, end):
    return Payment.unscoped.filter(restaurant=tenant, branch_id__in=branch_ids, status="succeeded", paid_at__date__gte=start, paid_at__date__lte=end)


def _refunds(tenant, branch_ids, start, end):
    return Refund.unscoped.filter(restaurant=tenant, branch_id__in=branch_ids, status="succeeded", created_at__date__gte=start, created_at__date__lte=end)


def build_report(tenant, branch_ids, start, end, group="day"):
    orders = _base_orders(tenant, branch_ids, start, end)
    o = orders.aggregate(
        n=Count("id"), completed=Count("id", filter=Q(status=Status.COMPLETED)), pending=Count("id", filter=Q(status__in=PENDING)),
        cancelled=Count("id", filter=Q(status=Status.CANCELLED)), booked=Sum("total", filter=~Q(status__in=DEAD)))
    # Receivable = total - still-paid amount - refunded amount (a refund settles that part; the customer does not owe it).
    refunded = Subquery(Refund.unscoped.filter(order=OuterRef("pk"), status="succeeded").values("order").annotate(t=Sum("amount")).values("t"),
                        output_field=DEC)
    due = (orders.filter(status__in=ACCEPTED).annotate(refunded=Coalesce(refunded, Value(Decimal("0")), output_field=DEC))
           .annotate(due=ExpressionWrapper(F("total") - F("amount_paid") - F("refunded"), output_field=DEC)).filter(due__gt=0))
    o["outstanding"] = due.aggregate(t=Sum("due"))["t"]
    pay = _payments(tenant, branch_ids, start, end)
    p = pay.aggregate(collected=Sum("amount"), cash=Sum("amount", filter=Q(method="cash")), mobile=Sum("amount", filter=Q(method="mobile_money")),
                      online=Sum("amount", filter=Q(order__source="online")), in_person=Sum("amount", filter=~Q(order__source="online")), n=Count("id"))
    ref = _refunds(tenant, branch_ids, start, end).aggregate(total=Sum("amount"), n=Count("id"))
    collected, refunds = p["collected"] or Decimal("0"), ref["total"] or Decimal("0")

    # time series (collected vs refunds), filled for daily grouping
    trunc = {"day": TruncDate, "week": TruncWeek, "month": TruncMonth}.get(group, TruncDate)
    col = {r["b"].date() if hasattr(r["b"], "date") else r["b"]: r["t"] for r in pay.annotate(b=trunc("paid_at")).values("b").annotate(t=Sum("amount"))}
    rfd = {r["b"].date() if hasattr(r["b"], "date") else r["b"]: r["t"] for r in _refunds(tenant, branch_ids, start, end).annotate(b=trunc("created_at")).values("b").annotate(t=Sum("amount"))}
    keys = sorted(set(col) | set(rfd))
    if group == "day":
        keys = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    series = [{"period": k.isoformat(), "collected": m(col.get(k)), "refunds": m(rfd.get(k)), "net": m((col.get(k) or Decimal("0")) - (rfd.get(k) or Decimal("0")))} for k in keys]

    items = (OrderItem.unscoped.filter(order__in=orders.exclude(status__in=DEAD)).values("product_name")
             .annotate(quantity=Sum("quantity"), revenue=Sum("line_total")).order_by("-quantity", "product_name")[:10])

    names = {u.pk: (u.full_name or u.email) for u in User.objects.filter(pk__in=set(
        list(pay.exclude(recorded_by=None).values_list("recorded_by", flat=True))
        + list(orders.exclude(cashier=None).values_list("cashier", flat=True))))}
    cashiers: dict[int, dict] = {}

    def row(uid):
        return cashiers.setdefault(uid, {"user_id": uid, "name": names.get(uid, "Unknown"), "cash": Decimal("0"), "mobile_money": Decimal("0"),
                                         "orders_entered": 0, "shifts_closed": 0, "variance": Decimal("0")})

    for r in pay.exclude(recorded_by=None).filter(method="cash").values("recorded_by").annotate(t=Sum("amount")):
        row(r["recorded_by"])["cash"] += r["t"]
    for r in pay.exclude(order__cashier=None).filter(method="mobile_money").values("order__cashier").annotate(t=Sum("amount")):
        row(r["order__cashier"])["mobile_money"] += r["t"]
    for r in orders.exclude(cashier=None).values("cashier").annotate(n=Count("id")):
        row(r["cashier"])["orders_entered"] = r["n"]
    for r in (Shift.unscoped.filter(restaurant=tenant, branch_id__in=branch_ids, status="closed", closed_at__date__gte=start, closed_at__date__lte=end)
              .values("cashier").annotate(n=Count("id"), v=Sum("variance"))):
        x = row(r["cashier"])
        x["shifts_closed"], x["variance"] = r["n"], r["v"] or Decimal("0")
    cashier_rows = sorted(({**c, "cash": m(c["cash"]), "mobile_money": m(c["mobile_money"]), "variance": m(c["variance"])} for c in cashiers.values()),
                          key=lambda c: -Decimal(c["cash"]) - Decimal(c["mobile_money"]))

    staff = (OrderStatusHistory.unscoped.filter(restaurant=tenant, order__branch_id__in=branch_ids, created_at__date__gte=start, created_at__date__lte=end)
             .exclude(actor=None).exclude(actor_role="customer").values("actor", "actor_role", "actor__full_name", "actor__email")
             .annotate(actions=Count("id")).order_by("-actions")[:15])

    low = Product.unscoped.filter(restaurant=tenant, is_archived=False, track_inventory=True, stock_quantity__lte=F("low_stock_threshold"))
    cust = orders.filter(customer__isnull=False).values("customer").annotate(n=Count("id"))

    per_branch = {b.pk: {"branch_id": b.pk, "name": b.name, "orders": 0, "booked": Decimal("0"), "collected": Decimal("0"), "refunds": Decimal("0")}
                  for b in Branch.unscoped.filter(pk__in=branch_ids)}
    for r in orders.values("branch").annotate(n=Count("id"), b=Sum("total", filter=~Q(status__in=DEAD))):
        per_branch[r["branch"]].update(orders=r["n"], booked=r["b"] or Decimal("0"))
    for r in pay.values("branch").annotate(t=Sum("amount")):
        per_branch[r["branch"]]["collected"] = r["t"]
    for r in _refunds(tenant, branch_ids, start, end).values("branch").annotate(t=Sum("amount")):
        per_branch[r["branch"]]["refunds"] = r["t"]

    return {
        "range": {"from": start.isoformat(), "to": end.isoformat(), "group": group},
        "orders": {"total": o["n"], "completed": o["completed"], "pending": o["pending"], "cancelled": o["cancelled"]},
        "sales": {"booked": m(o["booked"]), "collected": m(collected), "refunds": m(refunds), "net_collected": m(collected - refunds),
                  "outstanding": m(o["outstanding"]), "payments": p["n"], "refund_count": ref["n"]},
        "payment_breakdown": {"cash": m(p["cash"]), "mobile_money": m(p["mobile"]), "online": m(p["online"]), "in_person": m(p["in_person"])},
        "series": series,
        "top_products": [{"name": r["product_name"], "quantity": r["quantity"], "revenue": m(r["revenue"])} for r in items],
        "cashiers": cashier_rows,
        "staff_activity": [{"name": r["actor__full_name"] or r["actor__email"], "role": r["actor_role"], "actions": r["actions"]} for r in staff],
        "inventory": {"low_stock_count": low.count(), "low_stock": [{"name": x.name, "stock": x.stock_quantity, "alert_at": x.low_stock_threshold} for x in low.order_by("stock_quantity")[:10]]},
        "customers": {"ordering": cust.count(), "repeat": cust.filter(n__gt=1).count()},
        "by_branch": [{**b, "booked": m(b["booked"]), "collected": m(b["collected"]), "refunds": m(b["refunds"]),
                       "net_collected": m(b["collected"] - b["refunds"])} for b in sorted(per_branch.values(), key=lambda b: -b["collected"])],
    }


# ---- CSV export (no customer names, phones or emails) ------------------------------------------
def safe_cell(v):
    """Neutralise spreadsheet formula injection: cells that start with = + - @ are prefixed with an apostrophe."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


ORDER_HEADER = ["order_number", "created_at", "branch", "status", "fulfilment", "source", "payment_method", "payment_status",
                "subtotal", "discount", "tax", "delivery_fee", "total", "amount_paid"]
PAYMENT_HEADER = ["reference", "order_number", "branch", "method", "provider", "status", "amount", "paid_at", "recorded_by"]
MAX_ROWS = 50000


def export_rows(kind, tenant, branch_ids, start, end):
    if kind == "orders":
        yield ORDER_HEADER
        for x in _base_orders(tenant, branch_ids, start, end).select_related("branch").order_by("created_at")[:MAX_ROWS]:
            yield [x.number, x.created_at.isoformat(), x.branch.name, x.status, x.fulfilment, x.source, x.payment_method, x.payment_status,
                   x.subtotal, x.discount_total, x.tax_total, x.delivery_fee, x.total, x.amount_paid]
    else:
        yield PAYMENT_HEADER
        for x in _payments(tenant, branch_ids, start, end).select_related("order", "branch", "recorded_by").order_by("paid_at")[:MAX_ROWS]:
            yield [x.reference, x.order.number, x.branch.name, x.method, x.provider, x.status, x.amount, x.paid_at.isoformat() if x.paid_at else "",
                   (x.recorded_by.full_name or x.recorded_by.email) if x.recorded_by else ""]
