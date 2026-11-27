"""Payroll logic. All amounts are Decimal; every transition runs under a row lock and is audited.

Separation of duties (unless the restaurant has consciously enabled ``allow_admin_self_approval``):
* nobody prepares, approves or pays their OWN salary;
* whoever prepared a structure/record cannot approve it;
* whoever approved a record cannot also be the one who pays it;
* only people strictly above the employee in the role hierarchy (and, for managers, within their own branches) may handle that employee's pay.
"""
import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound

from apps.accounts.models import Membership, Role
from apps.accounts.permissions import accessible_branch_ids, can_assign_role, effective_role
from apps.core.models import audit, next_document_number
from apps.notifications.services import queue_email

from . import notices

from .models import (COMPONENT_TYPES, DEDUCTION_TYPES, EARNING_TYPES, PAY_METHODS, PayrollPeriod, PayrollRecord,
                     PayrollSequence, PayrollSettings, SalaryReceipt, SalaryStructure)

CENT = Decimal("0.01")
APPROVER_ROLES = (Role.PLATFORM_ADMIN, Role.RESTAURANT_ADMIN)
R = PayrollRecord.Status
SS = SalaryStructure.Status


def m(x) -> Decimal:
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def payroll_settings(tenant):
    return PayrollSettings.objects.get_or_create(restaurant=tenant)[0]


def _name(u):
    return (u.full_name or u.email) if u else None


# ---- authorisation ------------------------------------------------------------------------------------------
def employees_in_scope(request):
    qs = (Membership.objects.filter(restaurant=request.tenant).exclude(role=Role.CUSTOMER)
          .select_related("user").prefetch_related("branches"))
    role = effective_role(request)
    if role in APPROVER_ROLES:
        return qs
    mine = accessible_branch_ids(request)
    from apps.tenants.models import Branch

    outside = Branch.unscoped.filter(restaurant=request.tenant).exclude(pk__in=mine)
    return qs.filter(branches__in=mine).exclude(branches__in=outside).distinct()  # staff whose branches are ALL the manager's


def _self_ok(request, employee):
    return (employee.user_id == request.user.pk and effective_role(request) == Role.RESTAURANT_ADMIN
            and payroll_settings(request.tenant).allow_admin_self_approval)


def check_manage(request, employee):
    """Error message if the caller may not handle this employee's pay, else None."""
    role = effective_role(request)
    if employee.user_id == request.user.pk:
        return None if _self_ok(request, employee) else "You cannot handle your own pay."
    if role == Role.PLATFORM_ADMIN:
        return None
    if not can_assign_role(role, employee.role):
        return "You can only handle the pay of people below your own role."
    if role not in APPROVER_ROLES and not employees_in_scope(request).filter(pk=employee.pk).exists():
        return "This employee is outside your branches."
    return None


def _separation(request, preparer_id, employee):
    """Independent authorisation: the approver is neither the preparer nor the employee (unless the owner opted out)."""
    if payroll_settings(request.tenant).allow_admin_self_approval and effective_role(request) == Role.RESTAURANT_ADMIN:
        return None
    if preparer_id == request.user.pk:
        return "A different person must approve what you prepared."
    if employee.user_id == request.user.pk:
        return "You cannot approve your own pay."
    return None


def _need_approver_role(request):
    if effective_role(request) not in APPROVER_ROLES:
        raise serializers.ValidationError({"detail": "Only the restaurant administrator can approve payroll."})


def _fail(msg, field="detail"):
    raise serializers.ValidationError({field: msg})


# ---- components and pricing -----------------------------------------------------------------------------------
def clean_components(items, label="components"):
    out = []
    if len(items) > 30:
        _fail("At most 30 items are allowed.", label)
    for it in items:
        t, name, mode = it.get("type"), str(it.get("name", "")).strip(), it.get("mode", "fixed")
        if t not in COMPONENT_TYPES:
            _fail(f"Unknown item type: {t}.", label)
        if not name or len(name) > 80:
            _fail("Each item needs a name of up to 80 characters.", label)
        if mode not in ("fixed", "percent_of_basic"):
            _fail("Mode must be fixed or percent_of_basic.", label)
        try:
            amount = Decimal(str(it.get("amount")))
        except Exception:  # noqa: BLE001
            _fail("Amounts must be numbers.", label)
        if not amount.is_finite() or amount < 0 or (mode == "percent_of_basic" and amount > 100) or amount > Decimal("1000000000"):
            _fail("Amounts must be zero or more (percentages at most 100).", label)
        out.append({"type": t, "name": name, "mode": mode, "amount": str(m(amount))})
    return out


MAX_RULES = 10


def clean_rules(rules):
    """Validate statutory rules. Each rule: name, kind (percent | brackets), base (gross | basic | taxable), bearer (employee | employer),
    pre_tax (employee contributions that reduce the taxable base), rate (percent) or brackets [{up_to, rate}] with ascending
    up_to and a final open bracket (up_to null). The rates themselves are the restaurant's responsibility."""
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        _fail(f"Provide up to {MAX_RULES} rules.", "tax_rules")
    out = []
    for r in rules:
        if not isinstance(r, dict):
            _fail("Each rule must be an object.", "tax_rules")
        name = str(r.get("name", "")).strip()
        kind, base, bearer = r.get("kind"), r.get("base", "gross"), r.get("bearer", "employee")
        if not name or len(name) > 60:
            _fail("Each rule needs a name of up to 60 characters.", "tax_rules")
        if kind not in ("percent", "brackets") or base not in ("gross", "basic", "taxable") or bearer not in ("employee", "employer"):
            _fail(f"Rule {name}: invalid kind, base or bearer.", "tax_rules")
        if base == "taxable" and bearer == "employer":
            _fail(f"Rule {name}: employer contributions cannot use the taxable base.", "tax_rules")
        rule = {"name": name, "kind": kind, "base": base, "bearer": bearer, "pre_tax": bool(r.get("pre_tax", False)) and bearer == "employee", "enabled": bool(r.get("enabled", True))}
        if kind == "percent":
            try:
                rate = Decimal(str(r.get("rate")))
            except Exception:  # noqa: BLE001
                _fail(f"Rule {name}: the rate must be a number.", "tax_rules")
            if not rate.is_finite() or rate < 0 or rate > 100:
                _fail(f"Rule {name}: the rate must be between 0 and 100.", "tax_rules")
            rule["rate"] = str(rate.quantize(Decimal("0.0001")))
        else:
            bs, last = [], Decimal(-1)
            for i, b in enumerate(r.get("brackets") or []):
                try:
                    up = None if b.get("up_to") in (None, "") else Decimal(str(b["up_to"]))
                    rate = Decimal(str(b["rate"]))
                except Exception:  # noqa: BLE001
                    _fail(f"Rule {name}: invalid bracket.", "tax_rules")
                if rate < 0 or rate > 100 or (up is not None and (up <= last or up > Decimal("1000000000"))):
                    _fail(f"Rule {name}: brackets must ascend and rates must be 0-100.", "tax_rules")
                if up is None and i != len(r["brackets"]) - 1:
                    _fail(f"Rule {name}: only the last bracket may be open-ended.", "tax_rules")
                last = up if up is not None else last
                bs.append({"up_to": None if up is None else str(up.quantize(Decimal("0.01"))), "rate": str(rate.quantize(Decimal("0.0001")))})
            if not bs or bs[-1]["up_to"] is not None:
                _fail(f"Rule {name}: add a final bracket with no upper limit.", "tax_rules")
            rule["brackets"] = bs
        out.append(rule)
    return out


def _rule_amount(rule, base_amount):
    if rule["kind"] == "percent":
        return m(base_amount * Decimal(rule["rate"]) / Decimal(100))
    total, lower = Decimal("0"), Decimal("0")
    for b in rule["brackets"]:
        upper = Decimal(b["up_to"]) if b["up_to"] is not None else None
        if base_amount <= lower:
            break
        slice_ = (min(base_amount, upper) if upper is not None else base_amount) - lower
        total += slice_ * Decimal(b["rate"]) / Decimal(100)
        if upper is None:
            break
        lower = upper
    return m(total)


def apply_rules(rules, basic, gross):
    """Return (lines, employee_total, employer_total). Rules on the gross/basic base run first; 'taxable' rules then use
    gross minus the employee contributions flagged pre_tax."""
    lines, emp, boss, pre = [], Decimal("0"), Decimal("0"), Decimal("0")
    active = [r for r in rules if r.get("enabled", True)]
    for phase in ("direct", "taxable"):
        for r in active:
            if (r["base"] == "taxable") != (phase == "taxable"):
                continue
            base_amount = basic if r["base"] == "basic" else gross if r["base"] == "gross" else max(gross - pre, Decimal("0"))
            amt = _rule_amount(r, base_amount)
            if r["bearer"] == "employee":
                emp += amt
                pre += amt if r["pre_tax"] else Decimal("0")
            else:
                boss += amt
            lines.append({"source": "statutory", "type": "statutory" if r["bearer"] == "employee" else "employer_contribution", "name": r["name"], "amount": str(amt)})
    return lines, m(emp), m(boss)


def price(basic, structure_components, adjustments, rules=None):
    """Return (lines, totals). gross = basic + earnings; net = gross - deductions (including statutory). Never negative."""
    basic = m(basic)
    lines = [{"source": "structure", "type": "basic", "name": "Basic salary", "amount": str(basic)}]
    sums = {t: Decimal("0") for t in COMPONENT_TYPES}
    for source, items in (("structure", structure_components), ("adjustment", adjustments)):
        for c in items:
            amt = m(basic * Decimal(c["amount"]) / Decimal(100)) if c["mode"] == "percent_of_basic" else m(c["amount"])
            sums[c["type"]] += amt
            lines.append({"source": source, "type": c["type"], "name": c["name"], "amount": str(amt)})
    earnings = sum((sums[t] for t in EARNING_TYPES), Decimal("0"))
    deductions = sum((sums[t] for t in DEDUCTION_TYPES), Decimal("0"))
    gross = m(basic + earnings)
    stat_lines, statutory, employer = apply_rules(rules or [], basic, gross)
    lines += stat_lines
    deductions += statutory
    net = m(gross - deductions)
    if net < 0:
        _fail("Deductions are larger than the gross salary.", "adjustments")
    return lines, {"basic": basic, "allowances": m(sums["allowance"]), "bonuses": m(sums["bonus"]), "overtime": m(sums["overtime"]),
                   "other_earnings": m(sums["other_earning"]), "gross": gross, "deductions": m(deductions), "net": net, "statutory": statutory, "employer": employer}


# ---- salary structures ------------------------------------------------------------------------------------------------
def _member(request, membership_id, lock=False):
    qs = employees_in_scope(request)
    if lock:
        qs = Membership.objects.select_for_update().filter(pk__in=qs.values("pk"))
    emp = qs.filter(pk=membership_id).first()
    if emp is None:
        raise NotFound()
    problem = check_manage(request, emp)
    if problem:
        _fail(problem)
    return emp


@transaction.atomic
def create_structure(request, membership_id, data):
    emp = _member(request, membership_id, lock=True)
    if SalaryStructure.unscoped.filter(employee=emp, status=SS.PENDING).exists():
        _fail("There is already a salary change waiting for approval for this employee.")
    active = SalaryStructure.unscoped.filter(employee=emp, status=SS.ACTIVE).first()
    if active and data["effective_from"] <= active.effective_from:
        _fail("The new salary must start after the current one begins.", "effective_from")
    version = (SalaryStructure.unscoped.filter(employee=emp).order_by("-version").values_list("version", flat=True).first() or 0) + 1
    s = SalaryStructure.objects.create(
        restaurant=request.tenant, employee=emp, version=version, frequency=data["frequency"], basic_salary=m(data["basic_salary"]),
        components=clean_components(data["components"]), terms=data["terms"], currency=request.tenant.get_settings().currency,
        effective_from=data["effective_from"], created_by=request.user)
    audit("payroll.structure_created", actor=request.user, restaurant=request.tenant, obj=s, metadata={"employee": emp.pk, "version": version}, request=request)
    notices.structure(request, "submitted", s)
    return s


def _structure(request, sid):
    s = SalaryStructure.unscoped.select_for_update(of=("self",)).select_related("employee__user").filter(pk=sid, restaurant=request.tenant).first()
    if s is None:
        raise NotFound()
    problem = check_manage(request, s.employee)
    if problem:
        _fail(problem)
    return s


@transaction.atomic
def approve_structure(request, sid):
    _need_approver_role(request)
    s = _structure(request, sid)
    if s.status != SS.PENDING:
        _fail("Only a pending salary change can be approved.")
    problem = _separation(request, s.created_by_id, s.employee)
    if problem:
        _fail(problem)
    prev = SalaryStructure.unscoped.select_for_update().filter(employee=s.employee, status=SS.ACTIVE).first()
    if prev:
        prev.status, prev.effective_to = SS.SUPERSEDED, s.effective_from - timedelta(days=1)
        prev.save()
    s.status, s.approved_by, s.approved_at = SS.ACTIVE, request.user, timezone.now()
    s.save()
    audit("payroll.structure_approved", actor=request.user, restaurant=request.tenant, obj=s, metadata={"employee": s.employee.pk}, request=request)
    queue_email("salary_structure_updated", s.employee.user.email, {"name": s.employee.user.full_name, "effective": s.effective_from.isoformat()},
                restaurant=request.tenant, dedupe_key=f"payroll:structure:{s.pk}")
    notices.structure(request, "approved", s)
    return s


@transaction.atomic
def reject_structure(request, sid, reason):
    _need_approver_role(request)
    s = _structure(request, sid)
    if s.status != SS.PENDING:
        _fail("Only a pending salary change can be rejected.")
    if not reason.strip():
        _fail("Please give a reason.", "reason")
    s.status, s.reject_reason = SS.REJECTED, reason[:300]
    s.save()
    audit("payroll.structure_rejected", actor=request.user, restaurant=request.tenant, obj=s, metadata={"reason": reason[:200]}, request=request)
    notices.structure(request, "rejected", s, reason[:300])
    return s


# ---- periods and records ---------------------------------------------------------------------------------------------------
def month_bounds(period):
    return date(period.year, period.month, 1), date(period.year, period.month, calendar.monthrange(period.year, period.month)[1])


@transaction.atomic
def create_period(request, year, month):
    if PayrollPeriod.unscoped.filter(restaurant=request.tenant, year=year, month=month).exists():
        _fail("This payroll period already exists.")
    p = PayrollPeriod.objects.create(restaurant=request.tenant, year=year, month=month)
    audit("payroll.period_created", actor=request.user, restaurant=request.tenant, obj=p, request=request)
    return p


def pick_structure(emp, period):
    first, last = month_bounds(period)
    return (SalaryStructure.unscoped.filter(employee=emp, status__in=[SS.ACTIVE, SS.SUPERSEDED], effective_from__lte=last)
            .exclude(effective_to__lt=first).order_by("-effective_from").first())


def _branch_for(request, emp):
    ids = [b.pk for b in emp.branches.all()]
    if effective_role(request) in APPROVER_ROLES:
        return ids[0] if ids else None
    mine = accessible_branch_ids(request)
    return next((i for i in ids if i in mine), None)


def _period(request, period_id):
    p = PayrollPeriod.unscoped.filter(pk=period_id, restaurant=request.tenant).first()
    if p is None:
        raise NotFound()
    return p


@transaction.atomic
def upsert_record(request, period_id, membership_id, adjustments):
    period = _period(request, period_id)
    emp = _member(request, membership_id, lock=True)
    structure = pick_structure(emp, period)
    if structure is None:
        _fail("This employee has no approved salary structure for that month.")
    adj = clean_components(adjustments, "adjustments")
    lines, t = price(structure.basic_salary, structure.components, adj, payroll_settings(request.tenant).tax_rules)
    existing = PayrollRecord.unscoped.select_for_update().filter(period=period, employee=emp).first()
    if existing and existing.status not in (R.DRAFT, R.REJECTED, R.CANCELLED):
        _fail("This payroll record is already submitted or finalised and can no longer be edited.")
    fields = dict(structure=structure, branch_id=_branch_for(request, emp), currency=structure.currency, lines=lines, adjustments=adj,
                  basic_salary=t["basic"], total_allowances=t["allowances"], total_bonuses=t["bonuses"], total_overtime=t["overtime"],
                  total_other_earnings=t["other_earnings"], gross=t["gross"], total_deductions=t["deductions"], net=t["net"],
                  total_statutory=t["statutory"], employer_contributions=t["employer"],
                  status=R.DRAFT, prepared_by=request.user, submitted_at=None, approved_by=None, approved_at=None, decision_note="")
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        existing.save()
        rec = existing
    else:
        rec = PayrollRecord.objects.create(restaurant=request.tenant, period=period, employee=emp, **fields)
    audit("payroll.record_prepared", actor=request.user, restaurant=request.tenant, obj=rec, metadata={"net": str(rec.net), "structure": structure.version}, request=request)
    return rec


def draft_problem(request, period, emp, has_record):
    """Why no new draft can be generated for this employee, or None."""
    if has_record:
        return "Already has a record for this month."
    if not emp.is_active:
        return "This staff account is deactivated."
    problem = check_manage(request, emp)
    if problem:
        return problem
    if pick_structure(emp, period) is None:
        return "No approved salary for this month."
    return None


def candidates(request, period_id):
    """Every in-scope employee, and whether a draft can be generated for them this month."""
    period = _period(request, period_id)
    have = set(PayrollRecord.unscoped.filter(period=period).values_list("employee_id", flat=True))
    out = []
    for emp in employees_in_scope(request).order_by("user__full_name", "id"):
        problem = draft_problem(request, period, emp, emp.pk in have)
        out.append((emp, problem))
    return out


@transaction.atomic
def generate_period(request, period_id, membership_ids=None):
    """Create drafts for the chosen employees (all of them when none are chosen) who have an approved salary and no record yet.
    Returns the new records and, for chosen employees that were skipped, the reason."""
    period = _period(request, period_id)
    made, skipped = [], []
    chosen = None if membership_ids is None else set(membership_ids)
    for emp, problem in candidates(request, period.pk):
        if chosen is not None and emp.pk not in chosen:
            continue
        if problem:
            skipped.append({"id": emp.pk, "name": _name(emp.user), "reason": problem})
            continue
        made.append(upsert_record(request, period.pk, emp.pk, []))
    if chosen is not None:
        missing = chosen - {r.employee_id for r in made} - {x["id"] for x in skipped}
        skipped += [{"id": i, "name": "Unknown employee", "reason": "Not in your scope."} for i in sorted(missing)]
    if made:
        fresh = list(PayrollRecord.unscoped.filter(pk__in=[r.pk for r in made]).select_related("employee__user", "period", "prepared_by"))
        notices.records(request, "generated", fresh)
    return made, skipped


def _record(request, rid):
    rec = (PayrollRecord.unscoped.select_for_update(of=("self",)).select_related("employee__user", "period", "structure")
           .filter(pk=rid, restaurant=request.tenant).first())
    if rec is None:
        raise NotFound()
    problem = check_manage(request, rec.employee)
    if problem:
        _fail(problem)
    return rec


def _announce(request, event, rec, announce, reason=""):
    if announce:
        notices.records(request, event, [rec], reason)


@transaction.atomic
def submit_record(request, rid, announce=True):
    rec = _record(request, rid)
    if rec.status != R.DRAFT:
        _fail("Only a draft can be submitted for approval.")
    rec.status, rec.submitted_at = R.SUBMITTED, timezone.now()
    rec.save()
    audit("payroll.record_submitted", actor=request.user, restaurant=request.tenant, obj=rec, request=request)
    _announce(request, "submitted", rec, announce)
    return rec


@transaction.atomic
def approve_record(request, rid, announce=True):
    _need_approver_role(request)
    rec = _record(request, rid)
    if rec.status != R.SUBMITTED:
        _fail("Only a submitted record can be approved.")
    problem = _separation(request, rec.prepared_by_id, rec.employee)
    if problem:
        _fail(problem)
    rec.status, rec.approved_by, rec.approved_at = R.APPROVED, request.user, timezone.now()
    rec.save()
    audit("payroll.record_approved", actor=request.user, restaurant=request.tenant, obj=rec, metadata={"net": str(rec.net)}, request=request)
    _announce(request, "approved", rec, announce)
    return rec


@transaction.atomic
def reject_record(request, rid, reason, announce=True):
    _need_approver_role(request)
    rec = _record(request, rid)
    if rec.status != R.SUBMITTED:
        _fail("Only a submitted record can be rejected.")
    if not reason.strip():
        _fail("Please give a reason.", "reason")
    rec.status, rec.decision_note = R.REJECTED, reason[:300]
    rec.save()
    audit("payroll.record_rejected", actor=request.user, restaurant=request.tenant, obj=rec, metadata={"reason": reason[:200]}, request=request)
    _announce(request, "rejected", rec, announce, reason[:300])
    return rec


@transaction.atomic
def cancel_record(request, rid, reason, announce=True):
    rec = _record(request, rid)
    if rec.status in (R.PAID, R.CANCELLED):
        _fail("This record can no longer be cancelled.")
    if not reason.strip():
        _fail("Please give a reason.", "reason")
    rec.status, rec.decision_note = R.CANCELLED, reason[:300]
    rec.save()
    audit("payroll.record_cancelled", actor=request.user, restaurant=request.tenant, obj=rec, metadata={"reason": reason[:200]}, request=request)
    _announce(request, "cancelled", rec, announce, reason[:300])
    return rec


def payment_reference(tenant, period):
    """The system's own reference for a salary payment: unique and in sequence for this restaurant, e.g. PAY-202611-000042."""
    return next_document_number(tenant, "salary_pay", f"PAY-{period.year}{period.month:02d}")


@transaction.atomic
def pay_record(request, rid, data, announce=True):
    rec = _record(request, rid)
    if rec.status != R.APPROVED:
        _fail("Only an approved record can be paid.")
    if rec.approved_by_id == request.user.pk and not (payroll_settings(request.tenant).allow_admin_self_approval and effective_role(request) == Role.RESTAURANT_ADMIN):
        _fail("A different person from the approver must record the payment.")
    if data["method"] not in PAY_METHODS:
        _fail("Choose a payment method.", "method")
    if data["paid_on"] > timezone.now().date():
        _fail("The payment date cannot be in the future.", "paid_on")
    seq, _ = PayrollSequence.objects.select_for_update().get_or_create(restaurant=request.tenant)
    seq.last_number += 1
    seq.save(update_fields=["last_number"])
    rec.status, rec.paid_by, rec.paid_on = R.PAID, request.user, data["paid_on"]
    rec.payment_method = data["method"]
    rec.payment_reference = (data.get("reference") or "").strip() or payment_reference(request.tenant, rec.period)  # generated unless one is given
    rec.save()
    number = f"SAL-{seq.last_number:06d}"
    rec.receipt = SalaryReceipt.objects.create(restaurant=request.tenant, record=rec, number=number, data=receipt_data(rec, number, request.tenant))
    audit("payroll.record_paid", actor=request.user, restaurant=request.tenant, obj=rec, metadata={"net": str(rec.net), "method": rec.payment_method}, request=request)
    queue_email("salary_paid", rec.employee.user.email, {"name": rec.employee.user.full_name, "period": str(rec.period), "net": f"{rec.currency} {rec.net}",
                                                        "number": number, "url": f"{request.tenant.public_url}/manage/my-pay"},
                restaurant=request.tenant, dedupe_key=f"payroll:paid:{rec.pk}")
    _announce(request, "paid", rec, announce)
    return rec


BULK_ACTIONS = ("submit", "approve", "reject", "cancel", "pay")
PAST = {"submit": "submitted", "approve": "approved", "reject": "rejected", "cancel": "cancelled", "pay": "paid"}


def _reason_of(exc):
    detail = getattr(exc, "detail", None)
    while isinstance(detail, (dict, list)) and detail:
        detail = next(iter(detail.values())) if isinstance(detail, dict) else detail[0]
    return str(detail) if detail else "Not allowed."


@transaction.atomic
def bulk(request, period_id, action, record_ids, *, reason="", payment=None):
    """Apply one action to many records of a month. Each record is checked by the same rules as a single action and succeeds or
    fails on its own; the people concerned are then told once about everything that succeeded."""
    period = _period(request, period_id)
    mine = {r.pk: r for r in PayrollRecord.unscoped.filter(restaurant=request.tenant, period=period, pk__in=record_ids,
                                                           employee__in=employees_in_scope(request).values("pk")).select_related("employee__user")}
    done, failed = [], []
    for rid in dict.fromkeys(record_ids):  # the same record is never handled twice
        if rid not in mine:
            failed.append({"id": rid, "name": "Unknown record", "reason": "Not a record of this month that you can handle."})
            continue
        try:
            with transaction.atomic():
                if action == "submit":
                    rec = submit_record(request, rid, announce=False)
                elif action == "approve":
                    rec = approve_record(request, rid, announce=False)
                elif action == "reject":
                    rec = reject_record(request, rid, reason, announce=False)
                elif action == "cancel":
                    rec = cancel_record(request, rid, reason, announce=False)
                else:  # every payment gets its own generated reference
                    rec = pay_record(request, rid, {**payment, "reference": ""}, announce=False)
            done.append(rec)
        except (serializers.ValidationError, NotFound, PermissionError) as exc:
            failed.append({"id": rid, "name": _name(mine[rid].employee.user), "reason": _reason_of(exc)})
    notices.records(request, PAST[action], done, reason[:300] if action in ("reject", "cancel") else "")
    audit(f"payroll.bulk_{action}", actor=request.user, restaurant=request.tenant, obj=period,
          metadata={"done": [r.pk for r in done], "failed": len(failed)}, request=request)
    return done, failed


def receipt_data(rec, number, tenant):
    return {"number": number, "restaurant": tenant.name, "employee": _name(rec.employee.user), "role": rec.employee.role, "period": str(rec.period),
            "currency": rec.currency, "lines": rec.lines,
            "totals": {"basic": str(rec.basic_salary), "allowances": str(rec.total_allowances), "bonuses": str(rec.total_bonuses),
                       "overtime": str(rec.total_overtime), "other_earnings": str(rec.total_other_earnings), "gross": str(rec.gross),
                       "deductions": str(rec.total_deductions), "net": str(rec.net), "statutory": str(rec.total_statutory),
                       "employer_contributions": str(rec.employer_contributions)},
            "payment": {"method": rec.payment_method, "reference": rec.payment_reference, "paid_on": rec.paid_on.isoformat(),
                        "approved_by": _name(rec.approved_by), "paid_by": _name(rec.paid_by)}}
