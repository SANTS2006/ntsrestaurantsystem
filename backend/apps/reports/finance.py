"""Financial reporting, analytics and platform-wide reporting.

Definitions (also shown in the UI):
* sales received      = successful order payments in the period (by payment date) - successful refunds in the period
* catering received   = catering deposits and payments - catering refunds, by the date the money was received
* payroll paid        = net pay of payroll records marked paid in the period (by payment date)
* operating result    = sales received + catering received - payroll paid.
  ONLY payroll is recorded as an expense in this system (no purchasing, rent or utilities), so this is NOT a profit figure.
* receivables         = unpaid balance of accepted orders created in the period + open balances of accepted catering bookings
Everything is aggregated in the database; money is Decimal; the restaurant report is for restaurant administrators only
and is never branch-filtered (payroll and catering are restaurant-wide); analytics can be branch-scoped.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce, ExtractHour, ExtractWeekDay, TruncMonth

from apps.cashier.models import Shift
from apps.catering.models import CateringPayment, CateringRequest
from apps.finance.models import Expense, Invoice
from apps.catering.services import balance as catering_balance
from apps.orders.models import Order, Status
from apps.payments.models import Payment, Refund
from apps.payroll.models import PayrollRecord
from apps.tenants.models import Branch, Restaurant

from .services import ACCEPTED, DEAD, m, tenant_tz

DEC = DecimalField(max_digits=14, decimal_places=2)

ZERO = Decimal("0")
CAT_IN = ("deposit", "payment")


def _d(v):
    return v or ZERO


def _month_key(v):
    return (v.date() if hasattr(v, "date") else v).replace(day=1)


def financial_report(tenant, start, end):
    orders = Order.unscoped.filter(restaurant=tenant, created_at__date__gte=start, created_at__date__lte=end)
    live = orders.exclude(status__in=DEAD)
    o = live.aggregate(booked=Sum("total"), subtotal=Sum("subtotal"), discounts=Sum("discount_total"), tax=Sum("tax_total"), delivery=Sum("delivery_fee"), n=Count("id"))
    pay = Payment.unscoped.filter(restaurant=tenant, status="succeeded", paid_at__date__gte=start, paid_at__date__lte=end)
    refunds = Refund.unscoped.filter(restaurant=tenant, status="succeeded", created_at__date__gte=start, created_at__date__lte=end)
    collected = _d(pay.aggregate(t=Sum("amount"))["t"])
    refunded = _d(refunds.aggregate(t=Sum("amount"))["t"])
    by_method = {r["method"]: r["t"] for r in pay.values("method").annotate(t=Sum("amount"))}

    cat = CateringPayment.unscoped.filter(restaurant=tenant, received_on__gte=start, received_on__lte=end)
    cat_in = _d(cat.filter(kind__in=CAT_IN).aggregate(t=Sum("amount"))["t"])
    cat_out = _d(cat.filter(kind="refund").aggregate(t=Sum("amount"))["t"])

    paid_recs = PayrollRecord.unscoped.filter(restaurant=tenant, status="paid", paid_on__gte=start, paid_on__lte=end)
    pr = paid_recs.aggregate(net=Sum("net"), gross=Sum("gross"), n=Count("id"), stat=Sum("total_statutory"), boss=Sum("employer_contributions"))

    exp = Expense.unscoped.filter(restaurant=tenant, status="recorded", expense_date__gte=start, expense_date__lte=end)
    expenses_total = _d(exp.aggregate(t=Sum("amount"))["t"])
    by_category = [{"category": r["category__name"], "amount": m(r["t"])} for r in exp.values("category__name").annotate(t=Sum("amount")).order_by("-t")]
    sales_received = collected - refunded
    cat_received = cat_in - cat_out
    payroll_paid = _d(pr["net"])
    payroll_cost = payroll_paid + _d(pr["stat"]) + _d(pr["boss"])  # net to staff + tax withheld to remit + employer contributions
    result = sales_received + cat_received - payroll_cost - expenses_total

    # receivables: unpaid accepted orders created in the period, plus open balances of accepted catering bookings
    refunded_sq = Subquery(Refund.unscoped.filter(order=OuterRef("pk"), status="succeeded").values("order").annotate(t=Sum("amount")).values("t"), output_field=DEC)
    owed = _d(orders.filter(status__in=ACCEPTED).annotate(rf=Coalesce(refunded_sq, Value(ZERO), output_field=DEC))
              .annotate(due=ExpressionWrapper(F("total") - F("amount_paid") - F("rf"), output_field=DEC)).filter(due__gt=0).aggregate(t=Sum("due"))["t"])  # one query
    inv_open = sum((i.balance for i in Invoice.unscoped.filter(restaurant=tenant, status="issued")), ZERO)
    cat_open = ZERO
    for req in CateringRequest.unscoped.filter(restaurant=tenant, status__in=["accepted", "in_progress", "completed"]).prefetch_related("quotations", "payments"):
        b = Decimal(catering_balance(req)["balance"])
        if b > 0:
            cat_open += b

    # monthly trend
    months: dict[date, dict] = {}

    def slot(k):
        return months.setdefault(k, {"sales_received": ZERO, "catering_received": ZERO, "payroll_paid": ZERO})

    for r in pay.annotate(b=TruncMonth("paid_at")).values("b").annotate(t=Sum("amount")):
        slot(_month_key(r["b"]))["sales_received"] += r["t"]
    for r in refunds.annotate(b=TruncMonth("created_at")).values("b").annotate(t=Sum("amount")):
        slot(_month_key(r["b"]))["sales_received"] -= r["t"]
    for r in cat.annotate(b=TruncMonth("received_on")).values("b", "kind").annotate(t=Sum("amount")):
        slot(_month_key(r["b"]))["catering_received"] += -r["t"] if r["kind"] == "refund" else r["t"]
    for r in exp.annotate(b=TruncMonth("expense_date")).values("b").annotate(t=Sum("amount")):
        slot(_month_key(r["b"]))["payroll_paid"] += r["t"]  # trend shows total costs in this column
    for r in paid_recs.annotate(b=TruncMonth("paid_on")).values("b").annotate(t=Sum("net"), s=Sum("total_statutory"), e=Sum("employer_contributions")):
        slot(_month_key(r["b"]))["payroll_paid"] += r["t"] + r["s"] + r["e"]
    trend = [{"month": k.strftime("%Y-%m"), "sales_received": m(v["sales_received"]), "catering_received": m(v["catering_received"]),
              "payroll_paid": m(v["payroll_paid"]), "operating_result": m(v["sales_received"] + v["catering_received"] - v["payroll_paid"])}
             for k, v in sorted(months.items())]

    # per branch (orders and order payments only; catering and payroll are restaurant-wide)
    per = {b.pk: {"branch": b.name, "orders": 0, "booked": ZERO, "tax": ZERO, "collected": ZERO, "refunds": ZERO} for b in Branch.unscoped.filter(restaurant=tenant)}
    for r in live.values("branch").annotate(n=Count("id"), b=Sum("total"), t=Sum("tax_total")):
        per[r["branch"]].update(orders=r["n"], booked=r["b"], tax=r["t"])
    for r in pay.values("branch").annotate(t=Sum("amount")):
        per[r["branch"]]["collected"] = r["t"]
    for r in refunds.values("branch").annotate(t=Sum("amount")):
        per[r["branch"]]["refunds"] = r["t"]

    shifts = Shift.unscoped.filter(restaurant=tenant, status="closed", closed_at__date__gte=start, closed_at__date__lte=end)
    sh = shifts.aggregate(n=Count("id"), short=Sum("variance", filter=Q(variance__lt=0)), over=Sum("variance", filter=Q(variance__gt=0)))

    cur = tenant.get_settings().currency
    return {
        "range": {"from": start.isoformat(), "to": end.isoformat()}, "currency": cur, "timezone": tenant.get_settings().timezone,
        "orders": {"count": o["n"], "booked": m(o["booked"]), "subtotal": m(o["subtotal"]), "discounts": m(o["discounts"]), "tax": m(o["tax"]), "delivery_fees": m(o["delivery"])},
        "income": {"collected": m(collected), "refunds": m(refunded), "sales_received": m(sales_received),
                   "catering_received": m(cat_received), "total_received": m(sales_received + cat_received),
                   "by_method": {k: m(v) for k, v in sorted(by_method.items())}},
        "expenses": {"payroll_paid": m(payroll_paid), "payroll_gross": m(pr["gross"]), "payroll_records": pr["n"], "statutory_withheld": m(pr["stat"]),
                     "employer_contributions": m(pr["boss"]), "payroll_cost": m(payroll_cost),
                     "recorded": m(expenses_total), "by_category": by_category, "total": m(payroll_cost + expenses_total)},
        "operating_result": m(result),
        "receivables": {"orders": m(owed), "catering": m(cat_open), "invoices": m(inv_open), "total": m(owed + cat_open + inv_open)},
        "cash_control": {"shifts_closed": sh["n"], "shortages": m(sh["short"]), "overages": m(sh["over"]), "net_variance": m(_d(sh["short"]) + _d(sh["over"]))},
        "trend": trend,
        "by_branch": [{**b, "booked": m(b["booked"]), "tax": m(b["tax"]), "collected": m(b["collected"]), "refunds": m(b["refunds"]),
                       "net": m(_d(b["collected"]) - _d(b["refunds"]))} for b in sorted(per.values(), key=lambda b: b["branch"])],
        "notes": ["Costs are payroll plus recorded expenses (cash basis, no stock valuation or depreciation): the operating result is not an accounting profit.", f"Days follow the restaurant time zone ({tenant.get_settings().timezone})."],
    }


def finance_rows(tenant, start, end):
    r = financial_report(tenant, start, end)
    rows = [["section", "item", "amount"]]
    for sec, d in (("orders", r["orders"]), ("income", {k: v for k, v in r["income"].items() if k != "by_method"}), ("expenses", r["expenses"]),
                   ("receivables", r["receivables"]), ("cash_control", r["cash_control"])):
        rows += [[sec, k, v] for k, v in d.items()]
    rows += [["income_by_method", k, v] for k, v in r["income"]["by_method"].items()]
    rows.append(["result", "operating_result", r["operating_result"]])
    rows += [["trend", t["month"], t["operating_result"]] for t in r["trend"]]
    rows += [["branch_net", b["branch"], b["net"]] for b in r["by_branch"]]
    return rows


# ---- analytics (branch-scopable) ------------------------------------------------------------------------------
def analytics(tenant, branch_ids, start, end):
    orders = Order.unscoped.filter(restaurant=tenant, branch_id__in=branch_ids, created_at__date__gte=start, created_at__date__lte=end)
    live = orders.exclude(status__in=DEAD)
    tot = orders.aggregate(n=Count("id"), cancelled=Count("id", filter=Q(status=Status.CANCELLED)))
    lv = live.aggregate(n=Count("id"), booked=Sum("total"))
    hours = {r["h"]: r for r in live.annotate(h=ExtractHour("created_at")).values("h").annotate(n=Count("id"), t=Sum("total"))}
    days = {r["d"]: r for r in live.annotate(d=ExtractWeekDay("created_at")).values("d").annotate(n=Count("id"), t=Sum("total"))}
    names = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
    avg = (lv["booked"] / lv["n"]) if lv["n"] else ZERO
    cust = live.filter(customer__isnull=False).values("customer").annotate(n=Count("id"))
    ordering, repeat = cust.count(), cust.filter(n__gt=1).count()
    return {
        "range": {"from": start.isoformat(), "to": end.isoformat()}, "timezone": tenant.get_settings().timezone,
        "orders": tot["n"], "average_order_value": m(avg), "cancellation_rate_percent": str((Decimal(tot["cancelled"]) * 100 / tot["n"]).quantize(Decimal("0.1"))) if tot["n"] else "0.0",
        "by_hour": [{"hour": h, "orders": hours[h]["n"] if h in hours else 0, "booked": m(hours[h]["t"]) if h in hours else m(0)} for h in range(24)],
        "by_weekday": [{"day": names[d], "orders": days[d]["n"] if d in days else 0, "booked": m(days[d]["t"]) if d in days else m(0)} for d in (2, 3, 4, 5, 6, 7, 1)],
        "by_source": [{"source": r["source"], "orders": r["n"], "booked": m(r["t"])} for r in live.values("source").annotate(n=Count("id"), t=Sum("total")).order_by("-n")],
        "by_fulfilment": [{"fulfilment": r["fulfilment"], "orders": r["n"], "booked": m(r["t"])} for r in live.values("fulfilment").annotate(n=Count("id"), t=Sum("total")).order_by("-n")],
        "customers": {"ordering": ordering, "repeat": repeat, "repeat_rate_percent": str((Decimal(repeat) * 100 / ordering).quantize(Decimal("0.1"))) if ordering else "0.0"},
    }


# ---- platform-wide (platform administrators only; no customer or payroll data) -------------------------------------
def platform_report(start, end):
    rows = []
    for r in Restaurant.unscoped_objects.order_by("name"):
      with tenant_tz(r):
          o = Order.unscoped.filter(restaurant=r, created_at__date__gte=start, created_at__date__lte=end)
          lv = o.exclude(status__in=DEAD).aggregate(n=Count("id"), b=Sum("total"))
          pay = Payment.unscoped.filter(restaurant=r, status="succeeded", paid_at__date__gte=start, paid_at__date__lte=end).aggregate(t=Sum("amount"))["t"]
          rf = Refund.unscoped.filter(restaurant=r, status="succeeded", created_at__date__gte=start, created_at__date__lte=end).aggregate(t=Sum("amount"))["t"]
          rows.append({"id": r.pk, "name": r.name, "slug": r.slug, "status": r.status, "currency": r.get_settings().currency, "orders": lv["n"],
                       "booked": m(lv["b"]), "collected": m(pay), "refunds": m(rf), "net": m(_d(pay) - _d(rf))})
    totals: dict[str, dict] = {}
    for r in rows:
        t = totals.setdefault(r["currency"], {"currency": r["currency"], "restaurants": 0, "orders": 0, "booked": ZERO, "net": ZERO})
        t["restaurants"] += 1
        t["orders"] += r["orders"]
        t["booked"] += Decimal(r["booked"])
        t["net"] += Decimal(r["net"])
    joined = {_month_key(x["b"]).strftime("%Y-%m"): x["n"] for x in Restaurant.unscoped_objects.annotate(b=TruncMonth("created_at")).values("b").annotate(n=Count("id"))}
    return {
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "totals_by_currency": [{**t, "booked": m(t["booked"]), "net": m(t["net"])} for t in totals.values()],
        "restaurants": sorted(rows, key=lambda r: -Decimal(r["net"])),
        "new_restaurants_by_month": [{"month": k, "count": v} for k, v in sorted(joined.items())],
        "notes": ["Amounts are in each restaurant's own currency and are never summed across currencies.", "Each restaurant's days follow its own time zone."],
    }


_ = (F, timedelta)
