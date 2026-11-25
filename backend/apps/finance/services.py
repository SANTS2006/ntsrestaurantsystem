"""Expenses and invoices. Money is Decimal; recorded money is never edited or deleted (void instead)."""
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound

from apps.accounts.models import Role
from apps.accounts.permissions import accessible_branch_ids, effective_role
from apps.core.models import audit, next_document_number
from apps.notifications.services import queue_email

from .models import Expense, ExpenseCategory, Invoice, InvoiceLine, InvoicePayment

CENT = Decimal("0.01")
BIG = Decimal("1000000000")
ADMINS = (Role.RESTAURANT_ADMIN, Role.PLATFORM_ADMIN)


def money(x):
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def _fail(msg, field="detail"):
    raise serializers.ValidationError({field: msg})


def _today(request):
    return timezone.localdate()


# ---- expenses -----------------------------------------------------------------------------------------------
@transaction.atomic
def record_expense(request, d):
    role = effective_role(request)
    cat = ExpenseCategory.unscoped.filter(pk=d["category_id"], restaurant=request.tenant, is_active=True).first()
    if cat is None:
        _fail("Choose an active category.", "category_id")
    branch_id = d.get("branch_id")
    allowed = accessible_branch_ids(request)
    if branch_id is None and role not in ADMINS:
        _fail("Choose the branch this cost belongs to.", "branch_id")
    if branch_id is not None and branch_id not in allowed:
        raise NotFound()
    if d["amount"] <= 0 or d["amount"] >= BIG:
        _fail("Enter an amount above zero.", "amount")
    if d["expense_date"] > _today(request):
        _fail("The date cannot be in the future.", "expense_date")
    supplier = po = None
    if d.get("supplier_id"):
        from apps.procurement.models import Supplier

        supplier = Supplier.unscoped.filter(pk=d["supplier_id"], restaurant=request.tenant).first()
        if supplier is None:
            _fail("Unknown supplier.", "supplier_id")
    if d.get("purchase_order_id"):
        from apps.procurement.models import PurchaseOrder

        po = PurchaseOrder.unscoped.filter(pk=d["purchase_order_id"], restaurant=request.tenant, branch_id__in=allowed).first()
        if po is None:
            _fail("Unknown purchase order.", "purchase_order_id")
        supplier = supplier or po.supplier
    e = Expense.objects.create(restaurant=request.tenant, branch_id=branch_id, category=cat, description=d["description"].strip(), amount=money(d["amount"]),
                               currency=request.tenant.get_settings().currency, expense_date=d["expense_date"], method=d["method"], reference=d.get("reference", "").strip(),
                               supplier=supplier, purchase_order=po, created_by=request.user)
    audit("expense.recorded", actor=request.user, restaurant=request.tenant, obj=e, metadata={"amount": str(e.amount), "category": cat.name}, request=request)
    return e


@transaction.atomic
def void_expense(request, pk, reason):
    if effective_role(request) not in ADMINS:
        raise serializers.ValidationError({"detail": "Only the restaurant administrator can void an expense."})
    e = Expense.unscoped.select_for_update().filter(pk=pk, restaurant=request.tenant).first()
    if e is None:
        raise NotFound()
    if e.status == Expense.Status.VOID:
        _fail("This expense is already void.")
    if len(reason.strip()) < 3:
        _fail("Give a reason.", "reason")
    e.status, e.void_reason, e.voided_by = Expense.Status.VOID, reason.strip()[:300], request.user
    e.save()
    audit("expense.voided", actor=request.user, restaurant=request.tenant, obj=e, metadata={"reason": e.void_reason, "amount": str(e.amount)}, request=request)
    return e


# ---- invoices --------------------------------------------------------------------------------------------------
def _clean_lines(lines):
    if not lines:
        _fail("Add at least one line.", "lines")
    if len(lines) > 100:
        _fail("At most 100 lines.", "lines")
    out = []
    for l in lines:
        desc = l["description"].strip()
        if not desc:
            _fail("Every line needs a description.", "lines")
        qty, price = Decimal(l["quantity"]), money(l["unit_price"])
        if qty <= 0 or price < 0 or price >= BIG:
            _fail("Quantities must be above zero and prices zero or more.", "lines")
        out.append((desc, qty.quantize(CENT), price, money(qty * price)))
    return out


def _totals(inv, lines, rate):
    inv.subtotal = money(sum((l[3] for l in lines), Decimal("0")))
    inv.tax_rate_percent = Decimal(rate)
    inv.tax_total = money(inv.subtotal * inv.tax_rate_percent / Decimal(100))
    inv.total = money(inv.subtotal + inv.tax_total)


def _write_lines(inv, lines):
    InvoiceLine.unscoped.filter(invoice=inv).delete()
    for desc, qty, price, total in lines:
        InvoiceLine.objects.create(restaurant=inv.restaurant, invoice=inv, description=desc, quantity=qty, unit_price=price, line_total=total)


@transaction.atomic
def create_invoice(request, d):
    lines = _clean_lines(d["lines"])
    st = request.tenant.get_settings()
    inv = Invoice(restaurant=request.tenant, customer_name=d["customer_name"].strip(), customer_email=d.get("customer_email", ""), customer_address=d.get("customer_address", ""),
                  currency=st.currency, notes=d.get("notes", ""), created_by=request.user)
    _totals(inv, lines, d.get("tax_rate_percent", st.tax_rate_percent))
    inv.save()
    _write_lines(inv, lines)
    audit("invoice.created", actor=request.user, restaurant=request.tenant, obj=inv, metadata={"total": str(inv.total)}, request=request)
    return inv


def _invoice(request, pk, lock=True):
    qs = Invoice.unscoped.filter(pk=pk, restaurant=request.tenant)
    inv = (qs.select_for_update() if lock else qs).first()
    if inv is None:
        raise NotFound()
    return inv


@transaction.atomic
def update_draft(request, pk, d):
    inv = _invoice(request, pk)
    if inv.status != Invoice.Status.DRAFT:
        _fail("Only a draft invoice can be edited. Void it and create a new one instead.")
    for f in ("customer_name", "customer_email", "customer_address", "notes"):
        if f in d:
            setattr(inv, f, d[f].strip() if isinstance(d[f], str) else d[f])
    lines = _clean_lines(d["lines"]) if "lines" in d else [(l.description, l.quantity, l.unit_price, l.line_total) for l in inv.lines.all()]
    _totals(inv, lines, d.get("tax_rate_percent", inv.tax_rate_percent))
    inv.save()
    if "lines" in d:
        _write_lines(inv, lines)
    return inv


@transaction.atomic
def issue_invoice(request, pk, due_date):
    inv = _invoice(request, pk)
    if inv.status != Invoice.Status.DRAFT:
        _fail("Only a draft can be issued.")
    today = _today(request)
    if due_date < today:
        _fail("The due date cannot be in the past.", "due_date")
    if inv.total <= 0:
        _fail("An invoice must have a total above zero.")
    inv.number, inv.issue_date, inv.due_date, inv.status = next_document_number(request.tenant, "invoice", "INV"), today, due_date, Invoice.Status.ISSUED
    inv.save()
    audit("invoice.issued", actor=request.user, restaurant=request.tenant, obj=inv, metadata={"number": inv.number, "total": str(inv.total)}, request=request)
    if inv.customer_email:
        queue_email("invoice_issued", inv.customer_email, {"name": inv.customer_name, "number": inv.number, "total": f"{inv.currency} {inv.total}", "due": due_date.isoformat()},
                    restaurant=request.tenant, dedupe_key=f"invoice:{inv.pk}:issued")
    return inv


@transaction.atomic
def record_invoice_payment(request, pk, d):
    inv = _invoice(request, pk)
    if inv.status != Invoice.Status.ISSUED:
        _fail("Payments can only be recorded against an issued, unpaid invoice.")
    amount = money(d["amount"])
    if amount <= 0:
        _fail("Enter an amount above zero.", "amount")
    if amount > inv.balance:
        _fail(f"The balance is only {inv.balance}.", "amount")
    if d["received_on"] > _today(request):
        _fail("The date cannot be in the future.", "received_on")
    InvoicePayment.objects.create(restaurant=request.tenant, invoice=inv, amount=amount, method=d["method"], reference=d.get("reference", "").strip(), received_on=d["received_on"], recorded_by=request.user)
    inv.amount_paid += amount
    if inv.amount_paid >= inv.total:
        inv.status = Invoice.Status.PAID
    inv.save()
    audit("invoice.payment_recorded", actor=request.user, restaurant=request.tenant, obj=inv, metadata={"amount": str(amount), "number": inv.number}, request=request)
    return inv


@transaction.atomic
def void_invoice(request, pk, reason):
    if effective_role(request) not in ADMINS:
        raise serializers.ValidationError({"detail": "Only the restaurant administrator can void an invoice."})
    inv = _invoice(request, pk)
    if inv.status == Invoice.Status.VOID:
        _fail("This invoice is already void.")
    if inv.amount_paid > 0:
        _fail("An invoice with payments cannot be voided. Record the refund outside the system and keep the invoice as the record.")
    if len(reason.strip()) < 3:
        _fail("Give a reason.", "reason")
    inv.status, inv.void_reason = Invoice.Status.VOID, reason.strip()[:300]
    inv.save()
    audit("invoice.voided", actor=request.user, restaurant=request.tenant, obj=inv, metadata={"reason": inv.void_reason, "number": inv.number}, request=request)
    return inv
