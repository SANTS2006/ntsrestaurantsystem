import csv
import io
import json
from datetime import date

from django.core.serializers.json import DjangoJSONEncoder
from decimal import Decimal

from django.db.models import Count, Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Membership, Role
from apps.accounts.permissions import IsManagerOrAbove, IsRestaurantAdminOrAbove
from apps.core.idempotency import run_idempotent
from apps.core.models import audit
from apps.reports.services import safe_cell

from . import services
from .models import PAY_METHODS, PayrollPeriod, PayrollRecord, SalaryReceipt, SalaryStructure
from .services import employees_in_scope, m

MONEY = dict(max_digits=12, decimal_places=2)
R = PayrollRecord.Status


def structure_json(s):
    return {"id": s.pk, "employee_id": s.employee_id, "version": s.version, "status": s.status, "frequency": s.frequency, "basic_salary": str(s.basic_salary),
            "components": s.components, "terms": s.terms, "currency": s.currency, "effective_from": s.effective_from, "effective_to": s.effective_to,
            "created_by": services._name(s.created_by), "approved_by": services._name(s.approved_by), "reject_reason": s.reject_reason}


def record_json(r, with_lines=True):
    d = {"id": r.pk, "period": str(r.period), "period_id": r.period_id, "status": r.status, "currency": r.currency,
         "employee": {"id": r.employee_id, "name": services._name(r.employee.user), "role": r.employee.role, "email": r.employee.user.email},
         "branch": r.branch.name if r.branch_id else None, "basic_salary": str(r.basic_salary), "total_allowances": str(r.total_allowances),
         "total_bonuses": str(r.total_bonuses), "total_overtime": str(r.total_overtime), "total_other_earnings": str(r.total_other_earnings),
         "gross": str(r.gross), "total_deductions": str(r.total_deductions), "net": str(r.net), "total_statutory": str(r.total_statutory), "employer_contributions": str(r.employer_contributions), "structure_version": r.structure.version,
         "prepared_by": services._name(r.prepared_by), "approved_by": services._name(r.approved_by), "approved_at": r.approved_at,
         "decision_note": r.decision_note, "paid_by": services._name(r.paid_by), "paid_on": r.paid_on, "payment_method": r.payment_method,
         "payment_reference": r.payment_reference, "receipt_number": r.receipt.number if hasattr(r, "receipt") else None}
    if with_lines:
        d.update(lines=r.lines, adjustments=r.adjustments)
    return d


def records_qs(request):
    return (PayrollRecord.unscoped.filter(restaurant=request.tenant, employee__in=employees_in_scope(request).values("pk"))
            .select_related("employee__user", "period", "structure", "branch", "prepared_by", "approved_by", "paid_by"))


class Manage(APIView):
    permission_classes = [IsManagerOrAbove]


# ======================= settings ====================================================================
class SettingsView(APIView):
    permission_classes = [IsRestaurantAdminOrAbove]

    def get(self, request):
        st = services.payroll_settings(request.tenant)
        return Response({"allow_admin_self_approval": st.allow_admin_self_approval, "tax_rules": st.tax_rules})

    def patch(self, request):
        s = services.payroll_settings(request.tenant)
        changed = {}
        if "allow_admin_self_approval" in request.data:
            v = request.data["allow_admin_self_approval"]
            if not isinstance(v, bool):
                raise serializers.ValidationError({"allow_admin_self_approval": "Send true or false."})
            s.allow_admin_self_approval = changed["allow_admin_self_approval"] = v
        if "tax_rules" in request.data:
            s.tax_rules = services.clean_rules(request.data["tax_rules"])
            changed["tax_rules"] = s.tax_rules
        if not changed:
            raise serializers.ValidationError({"detail": "Nothing to change."})
        s.save()
        audit("payroll.settings_changed", actor=request.user, restaurant=request.tenant, metadata=changed, request=request)
        return self.get(request)


# ======================= employees and structures ====================================================
class EmployeesView(Manage):
    def get(self, request):
        out = []
        for e in employees_in_scope(request).order_by("user__full_name", "id"):
            sts = list(e.salary_structures.all())
            cur = next((s for s in sts if s.status == "active"), None)
            pend = next((s for s in sts if s.status == "pending"), None)
            out.append({"id": e.pk, "name": services._name(e.user), "email": e.user.email, "role": e.role, "is_active": e.is_active,
                        "branches": [b.name for b in e.branches.all()], "can_manage": services.check_manage(request, e) is None,
                        "current": structure_json(cur) if cur else None, "pending": structure_json(pend) if pend else None})
        return Response(out)


class ComponentInput(serializers.Serializer):
    type = serializers.CharField(max_length=20)
    name = serializers.CharField(max_length=80)
    mode = serializers.ChoiceField(choices=["fixed", "percent_of_basic"], default="fixed")
    amount = serializers.DecimalField(min_value=Decimal("0"), **MONEY)


class StructureInput(serializers.Serializer):
    membership_id = serializers.IntegerField()
    basic_salary = serializers.DecimalField(min_value=Decimal("0"), **MONEY)
    frequency = serializers.ChoiceField(choices=SalaryStructure.Frequency.values, default="monthly")
    effective_from = serializers.DateField()
    components = ComponentInput(many=True, required=False, default=list)
    terms = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class StructuresView(Manage):
    def get(self, request):
        qs = SalaryStructure.unscoped.filter(restaurant=request.tenant, employee__in=employees_in_scope(request).values("pk")).select_related("created_by", "approved_by")
        if request.query_params.get("employee", "").isdigit():
            qs = qs.filter(employee_id=int(request.query_params["employee"]))
        return Response([structure_json(s) for s in qs[:200]])

    def post(self, request):
        s = StructureInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        d["components"] = [dict(c, amount=str(c["amount"])) for c in d["components"]]
        st = services.create_structure(request, d.pop("membership_id"), d)
        return Response(structure_json(st), status=201)


class StructureActionView(Manage):
    def post(self, request, pk, act):
        if act == "approve":
            st = services.approve_structure(request, pk)
        elif act == "reject":
            st = services.reject_structure(request, pk, str(request.data.get("reason", "")))
        else:
            raise NotFound()
        return Response(structure_json(st))


# ======================= periods and records ================================================================
class PeriodsView(Manage):
    def get(self, request):
        ps = PayrollPeriod.unscoped.filter(restaurant=request.tenant)
        counts = {p: n for p, n in records_qs(request).values_list("period_id").annotate(n=Count("id"))}
        return Response([{"id": p.pk, "year": p.year, "month": p.month, "label": str(p), "records": counts.get(p.pk, 0)} for p in ps])

    def post(self, request):
        y, mth = request.data.get("year"), request.data.get("month")
        if not (isinstance(y, int) and isinstance(mth, int) and 2000 <= y <= 2100 and 1 <= mth <= 12):
            raise serializers.ValidationError({"detail": "Choose a valid year and month."})
        p = services.create_period(request, y, mth)
        return Response({"id": p.pk, "year": p.year, "month": p.month, "label": str(p), "records": 0}, status=201)


class PeriodDetailView(Manage):
    def get(self, request, pk):
        p = PayrollPeriod.unscoped.filter(pk=pk, restaurant=request.tenant).first()
        if p is None:
            raise NotFound()
        recs = records_qs(request).filter(period=p).order_by("employee__user__full_name")
        return Response({"id": p.pk, "label": str(p), "records": [record_json(r, with_lines=False) for r in recs]})


class PeriodGenerateView(Manage):
    def post(self, request, pk):
        made, skipped = services.generate_period(request, pk)
        return Response({"created": made, "skipped": skipped})


class RecordInput(serializers.Serializer):
    membership_id = serializers.IntegerField()
    adjustments = ComponentInput(many=True, required=False, default=list)


class PeriodRecordView(Manage):
    def post(self, request, pk):
        s = RecordInput(data=request.data)
        s.is_valid(raise_exception=True)
        adj = [dict(a, amount=str(a["amount"])) for a in s.validated_data["adjustments"]]
        rec = services.upsert_record(request, pk, s.validated_data["membership_id"], adj)
        return Response(record_json(records_qs(request).get(pk=rec.pk)), status=201)


class RecordView(Manage):
    def get(self, request, pk):
        r = records_qs(request).filter(pk=pk).first()
        if r is None:
            raise NotFound()
        return Response(record_json(r))


class PayInput(serializers.Serializer):
    method = serializers.ChoiceField(choices=PAY_METHODS)
    reference = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    paid_on = serializers.DateField()


class RecordActionView(Manage):
    def post(self, request, pk, act):
        reason = str(request.data.get("reason", ""))
        if act == "submit":
            rec = services.submit_record(request, pk)
        elif act == "approve":
            rec = services.approve_record(request, pk)
        elif act == "reject":
            rec = services.reject_record(request, pk, reason)
        elif act == "cancel":
            rec = services.cancel_record(request, pk, reason)
        elif act == "pay":
            s = PayInput(data=request.data)
            s.is_valid(raise_exception=True)

            def handler():
                r = services.pay_record(request, pk, dict(s.validated_data))
                return 200, json.loads(json.dumps(record_json(records_qs(request).get(pk=r.pk)), cls=DjangoJSONEncoder))  # JSON-safe for the idempotency store

            status, body = run_idempotent(request, f"payroll.pay:{pk}", request.headers.get("Idempotency-Key", ""), request.data, handler)
            return Response(body, status=status)
        else:
            raise NotFound()
        return Response(record_json(records_qs(request).get(pk=rec.pk)))


# ======================= payslip PDF ====================================================================
def render_pdf(d) -> bytes:
    from reportlab.lib.pagesizes import A5
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A5)
    w, h = A5
    y = h - 36

    def line(text, size=9, bold=False, gap=13, x=36):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(x, y, str(text)[:80])
        y -= gap

    cur = d["currency"]
    line(d["restaurant"], 14, True, 20)
    line(f'Salary receipt {d["number"]}', 10, True)
    line(f'{d["employee"]} · {d["period"]}')
    y -= 6
    for l in d["lines"]:
        sign = "-" if l["type"] in ("deduction", "other_deduction", "statutory") else ""
        note = " (paid by employer, not deducted)" if l["type"] == "employer_contribution" else ""
        line(f'{l["name"]}: {sign}{cur} {l["amount"]}{note}')
    y -= 6
    t = d["totals"]
    line(f'Gross: {cur} {t["gross"]}   Deductions: {cur} {t["deductions"]}', 10, True)
    line(f'NET PAY: {cur} {t["net"]}', 12, True, 18)
    p = d["payment"]
    line(f'Paid {p["paid_on"]} by {p["method"].replace("_", " ")}' + (f' · ref {p["reference"]}' if p["reference"] else ""))
    line(f'Approved by {p["approved_by"]} · Paid by {p["paid_by"]}', 8)
    c.showPage()
    c.save()
    return buf.getvalue()


def _pdf_response(receipt):
    resp = HttpResponse(render_pdf(receipt.data), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{receipt.number}.pdf"'
    resp["Cache-Control"] = "private, no-store"
    return resp


class RecordPdfView(Manage):
    def get(self, request, pk):
        r = records_qs(request).filter(pk=pk, status=R.PAID).first()
        if r is None:
            raise NotFound()
        audit("payroll.receipt_downloaded", actor=request.user, restaurant=request.tenant, obj=r, request=request)
        return _pdf_response(SalaryReceipt.unscoped.get(record=r))


# ======================= reports ======================================================================
def _range(request):
    p = request.query_params
    try:
        y = int(p.get("year", timezone.now().year))
        mo = int(p["month"]) if p.get("month") else None
    except ValueError:
        raise serializers.ValidationError({"detail": "Invalid year or month."})
    return y, mo


class SummaryView(Manage):
    def get(self, request):
        y, mo = _range(request)
        qs = records_qs(request).filter(period__year=y).exclude(status__in=[R.CANCELLED])
        if mo:
            qs = qs.filter(period__month=mo)
        by_status = {s: {"count": 0, "gross": m(0), "deductions": m(0), "net": m(0)} for s in R.values}
        for r in qs.values("status").annotate(n=Count("id"), g=Sum("gross"), d=Sum("total_deductions"), t=Sum("net")):
            by_status[r["status"]] = {"count": r["n"], "gross": m(r["g"]), "deductions": m(r["d"]), "net": m(r["t"])}
        branches = [{"branch": r["branch__name"] or "Restaurant-wide", "count": r["n"], "gross": str(m(r["g"])), "net": str(m(r["t"]))}
                    for r in qs.values("branch__name").annotate(n=Count("id"), g=Sum("gross"), t=Sum("net")).order_by("branch__name")]
        paid = by_status[R.PAID]
        return Response({"year": y, "month": mo, "by_status": {k: {kk: (str(vv) if isinstance(vv, Decimal) else vv) for kk, vv in v.items()} for k, v in by_status.items()},
                         "by_branch": branches, "paid_net": str(paid["net"]), "committed_net": str(m(sum((by_status[s]["net"] for s in (R.APPROVED, R.PAID)), Decimal("0"))))})


class ExportView(Manage):
    def get(self, request):
        y, mo = _range(request)
        qs = records_qs(request).filter(period__year=y)
        if mo:
            qs = qs.filter(period__month=mo)
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="payroll-{y}{f"-{mo:02d}" if mo else ""}.csv"'
        w = csv.writer(resp)
        w.writerow(["period", "employee", "role", "branch", "status", "basic", "allowances", "bonuses", "overtime", "other_earnings", "gross", "deductions", "net",
                    "paid_on", "method", "reference", "receipt"])
        for r in qs.order_by("period__month", "employee__user__full_name")[:20000]:
            w.writerow([safe_cell(c) for c in [str(r.period), services._name(r.employee.user), r.employee.role, r.branch.name if r.branch_id else "", r.status, r.basic_salary,
                                                r.total_allowances, r.total_bonuses, r.total_overtime, r.total_other_earnings, r.gross, r.total_deductions, r.net,
                                                r.paid_on or "", r.payment_method, r.payment_reference, r.receipt.number if hasattr(r, "receipt") else ""]])
        audit("payroll.exported", actor=request.user, restaurant=request.tenant, metadata={"year": y, "month": mo}, request=request)
        return resp


# ======================= employee self-service ===========================================================
def my_membership(request):
    t = request.tenant
    if t is None:
        raise NotFound()
    mem = Membership.objects.filter(user=request.user, restaurant=t, is_active=True).exclude(role=Role.CUSTOMER).first()
    if mem is None:
        raise serializers.ValidationError({"detail": "Pay information is only available to staff."})
    return mem


class MyPayView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        mem = my_membership(request)
        cur = mem.salary_structures.filter(status="active").first()
        slips = (PayrollRecord.unscoped.filter(employee=mem, status__in=[R.APPROVED, R.PAID]).select_related("employee__user", "period", "structure", "branch", "prepared_by", "approved_by", "paid_by"))
        return Response({"structure": structure_json(cur) if cur else None, "slips": [record_json(r) for r in slips]})


class MyPdfView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        mem = my_membership(request)
        r = PayrollRecord.unscoped.filter(pk=pk, employee=mem, status=R.PAID).first()  # only the employee's own, paid slips
        if r is None:
            raise NotFound()
        return _pdf_response(SalaryReceipt.unscoped.get(record=r))


_ = date
