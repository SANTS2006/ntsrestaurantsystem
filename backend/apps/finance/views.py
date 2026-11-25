import io
from decimal import Decimal

from django.db.models import Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManagerOrAbove, IsRestaurantAdminOrAbove, accessible_branch_ids, effective_role
from apps.accounts.models import Role
from apps.core.idempotency import run_idempotent
from apps.core.models import audit
from apps.core.pagination import StandardPagination

from . import services
from .models import METHODS, Expense, ExpenseCategory, Invoice

ADMINS = (Role.RESTAURANT_ADMIN, Role.PLATFORM_ADMIN)
METHOD_KEYS = [k for k, _ in METHODS]
MONEY = dict(max_digits=12, decimal_places=2, min_value=Decimal("0.00"))


class Manage(APIView):
    permission_classes = [IsManagerOrAbove]


# ------------------------------------------------------------------------------------------------ categories
class CategoriesView(Manage):
    def get(self, request):
        return Response([{"id": c.pk, "name": c.name, "is_active": c.is_active} for c in ExpenseCategory.unscoped.filter(restaurant=request.tenant)])

    def post(self, request):
        if effective_role(request) not in ADMINS:
            raise serializers.ValidationError({"detail": "Only the restaurant administrator manages categories."})
        name = str(request.data.get("name", "")).strip()
        if not name or len(name) > 80:
            raise serializers.ValidationError({"name": "Enter a name of up to 80 characters."})
        if ExpenseCategory.unscoped.filter(restaurant=request.tenant, name__iexact=name).exists():
            raise serializers.ValidationError({"name": "This category already exists."})
        c = ExpenseCategory.objects.create(restaurant=request.tenant, name=name)
        return Response({"id": c.pk, "name": c.name, "is_active": True}, status=201)


# ------------------------------------------------------------------------------------------------ expenses
class ExpenseInput(serializers.Serializer):
    category_id = serializers.IntegerField()
    branch_id = serializers.IntegerField(required=False, allow_null=True)
    description = serializers.CharField(max_length=200)
    amount = serializers.DecimalField(**MONEY)
    expense_date = serializers.DateField()
    method = serializers.ChoiceField(choices=METHOD_KEYS)
    reference = serializers.CharField(max_length=60, required=False, allow_blank=True)
    supplier_id = serializers.IntegerField(required=False, allow_null=True)
    purchase_order_id = serializers.IntegerField(required=False, allow_null=True)


def expense_json(e):
    return {"id": e.pk, "category": e.category.name, "category_id": e.category_id, "branch": e.branch.name if e.branch_id else None, "branch_id": e.branch_id, "description": e.description,
            "amount": str(e.amount), "currency": e.currency, "expense_date": e.expense_date, "method": e.method, "reference": e.reference, "status": e.status, "void_reason": e.void_reason,
            "supplier": e.supplier.name if e.supplier_id else None, "purchase_order": e.purchase_order.number if e.purchase_order_id else None,
            "created_by": (e.created_by.full_name or e.created_by.email) if e.created_by else None}


def scoped_expenses(request):
    qs = Expense.unscoped.filter(restaurant=request.tenant).select_related("category", "branch", "supplier", "purchase_order", "created_by")
    if effective_role(request) not in ADMINS:
        qs = qs.filter(branch_id__in=accessible_branch_ids(request))  # restaurant-wide costs are visible to the administrator only
    return qs


class ExpensesView(Manage):
    def get(self, request):
        qs = scoped_expenses(request)
        p = request.query_params
        if p.get("category", "").isdigit():
            qs = qs.filter(category_id=int(p["category"]))
        if p.get("status") in ("recorded", "void"):
            qs = qs.filter(status=p["status"])
        for key, lk in (("from", "expense_date__gte"), ("to", "expense_date__lte")):
            if p.get(key):
                try:
                    qs = qs.filter(**{lk: timezone.datetime.fromisoformat(p[key]).date()})
                except ValueError:
                    raise serializers.ValidationError({key: "Use the format YYYY-MM-DD."})
        if q := p.get("q", "").strip()[:100]:
            qs = qs.filter(description__icontains=q)
        pager = StandardPagination()
        page = pager.paginate_queryset(qs, request)
        total = qs.filter(status="recorded").aggregate(t=Sum("amount"))["t"] or Decimal("0")
        resp = pager.get_paginated_response([expense_json(e) for e in page])
        resp.data["total_recorded"] = str(total.quantize(Decimal("0.01")))
        return resp

    def post(self, request):
        s = ExpenseInput(data=request.data)
        s.is_valid(raise_exception=True)
        e = services.record_expense(request, dict(s.validated_data))
        return Response(expense_json(Expense.unscoped.select_related("category", "branch", "supplier", "purchase_order", "created_by").get(pk=e.pk)), status=201)


class ExpenseVoidView(Manage):
    def post(self, request, pk):
        e = services.void_expense(request, pk, str(request.data.get("reason", "")))
        return Response(expense_json(Expense.unscoped.select_related("category", "branch", "supplier", "purchase_order", "created_by").get(pk=e.pk)))


# ------------------------------------------------------------------------------------------------ invoices
class LineIn(serializers.Serializer):
    description = serializers.CharField(max_length=200)
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    unit_price = serializers.DecimalField(**MONEY)


class InvoiceInput(serializers.Serializer):
    customer_name = serializers.CharField(max_length=150)
    customer_email = serializers.EmailField(required=False, allow_blank=True)
    customer_address = serializers.CharField(max_length=300, required=False, allow_blank=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)
    tax_rate_percent = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100, required=False)
    lines = LineIn(many=True)


class InvoicePatch(InvoiceInput):
    customer_name = serializers.CharField(max_length=150, required=False)
    lines = LineIn(many=True, required=False)


def invoice_json(i, detail=True):
    overdue = i.status == "issued" and i.due_date is not None and i.due_date < timezone.localdate()
    d = {"id": i.pk, "number": i.number, "status": i.status, "overdue": overdue, "customer_name": i.customer_name, "customer_email": i.customer_email, "issue_date": i.issue_date, "due_date": i.due_date,
         "currency": i.currency, "subtotal": str(i.subtotal), "tax_rate_percent": str(i.tax_rate_percent), "tax_total": str(i.tax_total), "total": str(i.total), "amount_paid": str(i.amount_paid),
         "balance": str(i.balance), "void_reason": i.void_reason, "created_at": i.created_at}
    if detail:
        d.update(customer_address=i.customer_address, notes=i.notes,
                 lines=[{"description": l.description, "quantity": str(l.quantity), "unit_price": str(l.unit_price), "line_total": str(l.line_total)} for l in i.lines.all()],
                 payments=[{"amount": str(p.amount), "method": p.method, "reference": p.reference, "received_on": p.received_on} for p in i.payments.all()])
    return d


class InvoicesView(Manage):
    def get(self, request):
        qs = Invoice.unscoped.filter(restaurant=request.tenant)
        p = request.query_params
        if p.get("status") in ("draft", "issued", "paid", "void"):
            qs = qs.filter(status=p["status"])
        if p.get("overdue") == "1":
            qs = qs.filter(status="issued", due_date__lt=timezone.localdate())
        if q := p.get("q", "").strip()[:100]:
            qs = qs.filter(customer_name__icontains=q) | qs.filter(number__icontains=q)
        pager = StandardPagination()
        page = pager.paginate_queryset(qs, request)
        out = Invoice.unscoped.filter(restaurant=request.tenant, status="issued")
        resp = pager.get_paginated_response([invoice_json(i, detail=False) for i in page])
        resp.data["outstanding"] = str(sum((i.balance for i in out), Decimal("0")).quantize(Decimal("0.01")))
        return resp

    def post(self, request):
        s = InvoiceInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        d["lines"] = [dict(l) for l in d["lines"]]
        return Response(invoice_json(services.create_invoice(request, d)), status=201)


class InvoiceView(Manage):
    def _get(self, request, pk):
        i = Invoice.unscoped.filter(pk=pk, restaurant=request.tenant).first()
        if i is None:
            raise NotFound()
        return i

    def get(self, request, pk):
        return Response(invoice_json(self._get(request, pk)))

    def patch(self, request, pk):
        s = InvoicePatch(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        if "lines" in d:
            d["lines"] = [dict(l) for l in d["lines"]]
        services.update_draft(request, pk, d)
        return Response(invoice_json(self._get(request, pk)))


class PayInput(serializers.Serializer):
    amount = serializers.DecimalField(**MONEY)
    method = serializers.ChoiceField(choices=METHOD_KEYS)
    reference = serializers.CharField(max_length=60, required=False, allow_blank=True)
    received_on = serializers.DateField()


class InvoiceActionView(Manage):
    def post(self, request, pk, act):
        if act == "issue":
            due = serializers.DateField().run_validation(request.data.get("due_date")) if request.data.get("due_date") else None
            if due is None:
                raise serializers.ValidationError({"due_date": "Choose a due date."})
            services.issue_invoice(request, pk, due)
        elif act == "void":
            services.void_invoice(request, pk, str(request.data.get("reason", "")))
        elif act == "payments":
            s = PayInput(data=request.data)
            s.is_valid(raise_exception=True)

            def handler():
                inv = services.record_invoice_payment(request, pk, dict(s.validated_data))
                import json

                from django.core.serializers.json import DjangoJSONEncoder

                return 200, json.loads(json.dumps(invoice_json(inv), cls=DjangoJSONEncoder))

            status, body = run_idempotent(request, f"invoice.pay:{pk}", request.headers.get("Idempotency-Key", ""), request.data, handler)
            return Response(body, status=status)
        else:
            raise NotFound()
        return Response(invoice_json(Invoice.unscoped.get(pk=pk)))


def render_invoice_pdf(inv, restaurant) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    y = h - 50

    def line(text, size=10, bold=False, gap=15, x=50):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(x, y, str(text)[:95])
        y -= gap

    line(restaurant.name, 18, True, 26)
    line(f"INVOICE {inv.number}" + ("  (VOID)" if inv.status == "void" else ""), 13, True, 20)
    line(f"Issued {inv.issue_date}   Due {inv.due_date}")
    y -= 8
    line(f"Bill to: {inv.customer_name}", 11, True)
    if inv.customer_address:
        line(inv.customer_address)
    y -= 10
    cur = inv.currency
    for l in inv.lines.all():
        line(f"{l.description}   {l.quantity} x {cur} {l.unit_price} = {cur} {l.line_total}")
    y -= 8
    line(f"Subtotal: {cur} {inv.subtotal}", 10, False, 14)
    line(f"Tax ({inv.tax_rate_percent}%): {cur} {inv.tax_total}", 10, False, 14)
    line(f"TOTAL: {cur} {inv.total}", 13, True, 18)
    line(f"Paid: {cur} {inv.amount_paid}    Balance due: {cur} {inv.balance}", 11, True)
    if inv.notes:
        y -= 8
        line(inv.notes, 9)
    c.showPage()
    c.save()
    return buf.getvalue()


class InvoicePdfView(Manage):
    def get(self, request, pk):
        inv = Invoice.unscoped.filter(pk=pk, restaurant=request.tenant).exclude(status="draft").first()
        if inv is None:
            raise NotFound()
        resp = HttpResponse(render_invoice_pdf(inv, request.tenant), content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="{inv.number}.pdf"'
        resp["Cache-Control"] = "private, no-store"
        audit("invoice.pdf_downloaded", actor=request.user, restaurant=request.tenant, obj=inv, request=request)
        return resp


_ = IsRestaurantAdminOrAbove
