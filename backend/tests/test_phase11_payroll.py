import datetime
import uuid
from decimal import Decimal

import pytest

from apps.accounts.models import Membership, Role, User
from apps.notifications.models import EmailLog
from apps.payroll.models import PayrollRecord, SalaryReceipt, SalaryStructure
from apps.payroll.services import price
from tests.conftest import PW, client_for

P = "/api/v1/payroll"
TODAY = datetime.date.today()


def mem(user, restaurant):
    return Membership.objects.get(user=user, restaurant=restaurant)


def call(c, method, url, data=None, **kw):
    r = getattr(c, method)(url, data, format="json", **kw)
    return r


def structure(c, emp, basic="1000.00", components=None, eff="2024-01-01"):
    return call(c, "post", f"{P}/structures/", {"membership_id": emp.pk, "basic_salary": basic, "effective_from": eff, "components": components or []})


def activate(world, user, basic="1000.00", components=None, eff="2024-01-01"):
    """Manager proposes, admin approves."""
    emp = mem(user, world["a"])
    r = structure(client_for(world["mgr_a1"], "alpha"), emp, basic, components, eff)
    assert r.status_code == 201, r.content
    r2 = call(client_for(world["admin_a"], "alpha"), "post", f"{P}/structures/{r.json()['data']['id']}/approve/")
    assert r2.status_code == 200, r2.content
    return emp


def prepared(world, user, adjustments=None, year=2024, month=3):
    emp = activate(world, user)
    c = client_for(world["mgr_a1"], "alpha")
    made = call(c, "post", f"{P}/periods/", {"year": year, "month": month})
    if made.status_code == 201:
        pid = made.json()["data"]["id"]
    else:  # the period already exists (a second employee in the same month)
        pid = next(p["id"] for p in c.get(f"{P}/periods/").json()["data"] if p["year"] == year and p["month"] == month)
    r = call(c, "post", f"{P}/periods/{pid}/records/", {"membership_id": emp.pk, "adjustments": adjustments or []})
    assert r.status_code == 201, r.content
    return emp, pid, r.json()["data"]["id"]


def approved(world, user, **kw):
    emp, pid, rid = prepared(world, user, **kw)
    assert call(client_for(world["mgr_a1"], "alpha"), "post", f"{P}/records/{rid}/submit/").status_code == 200
    assert call(client_for(world["admin_a"], "alpha"), "post", f"{P}/records/{rid}/approve/").status_code == 200
    return emp, pid, rid


def pay(c, rid, key=None, **over):
    body = {"method": "cash", "reference": "", "paid_on": TODAY.isoformat(), **over}
    return c.post(f"{P}/records/{rid}/pay/", body, format="json", HTTP_IDEMPOTENCY_KEY=key or uuid.uuid4().hex)


# ---------------- calculation ----------------
def test_price_is_exact_and_uses_decimals():
    comps = [{"type": "allowance", "name": "Transport", "mode": "fixed", "amount": "50.25"},
             {"type": "bonus", "name": "Perf", "mode": "percent_of_basic", "amount": "10"},
             {"type": "deduction", "name": "Tax", "mode": "percent_of_basic", "amount": "7.5"}]
    adj = [{"type": "overtime", "name": "OT", "mode": "fixed", "amount": "20.10"},
           {"type": "other_earning", "name": "Tips", "mode": "fixed", "amount": "5.00"},
           {"type": "other_deduction", "name": "Advance", "mode": "fixed", "amount": "100.00"}]
    lines, t = price(Decimal("1000.00"), comps, adj)
    assert t["allowances"] == Decimal("50.25") and t["bonuses"] == Decimal("100.00") and t["overtime"] == Decimal("20.10")
    assert t["gross"] == Decimal("1175.35")
    assert t["deductions"] == Decimal("175.00")
    assert t["net"] == Decimal("1000.35")
    assert all(isinstance(v, Decimal) for v in t.values())


def test_percent_rounds_half_up():
    _, t = price(Decimal("100.05"), [{"type": "bonus", "name": "b", "mode": "percent_of_basic", "amount": "10"}], [])
    assert t["bonuses"] == Decimal("10.01")  # 10.005 -> 10.01


def test_negative_net_rejected(world):
    emp = activate(world, world["cashier_a1"])
    c = client_for(world["mgr_a1"], "alpha")
    pid = call(c, "post", f"{P}/periods/", {"year": 2024, "month": 4}).json()["data"]["id"]
    r = call(c, "post", f"{P}/periods/{pid}/records/", {"membership_id": emp.pk, "adjustments": [{"type": "deduction", "name": "Big", "amount": "5000"}]})
    assert r.status_code == 400


def test_bad_inputs_rejected(world):
    c = client_for(world["mgr_a1"], "alpha")
    emp = mem(world["cashier_a1"], world["a"])
    assert structure(c, emp, basic="-5").status_code == 400
    assert structure(c, emp, components=[{"type": "nonsense", "name": "x", "amount": "1"}]).status_code == 400
    assert structure(c, emp, components=[{"type": "bonus", "name": "x", "mode": "percent_of_basic", "amount": "150"}]).status_code == 400
    assert call(c, "post", f"{P}/periods/", {"year": 2024, "month": 13}).status_code == 400


# ---------------- structures / versioning ----------------
def test_structure_needs_approval_and_versions(world):
    emp = mem(world["cashier_a1"], world["a"])
    c = client_for(world["mgr_a1"], "alpha")
    s1 = structure(c, emp).json()["data"]
    assert s1["status"] == "pending" and s1["version"] == 1
    assert structure(c, emp, eff="2024-06-01").status_code == 400  # one pending at a time
    admin = client_for(world["admin_a"], "alpha")
    assert call(admin, "post", f"{P}/structures/{s1['id']}/approve/").status_code == 200
    s2 = structure(c, emp, basic="1500.00", eff="2024-07-01").json()["data"]
    assert s2["version"] == 2
    assert call(admin, "post", f"{P}/structures/{s2['id']}/approve/").status_code == 200
    old = SalaryStructure.unscoped.get(pk=s1["id"])
    assert old.status == "superseded" and old.effective_to == datetime.date(2024, 6, 30)
    assert SalaryStructure.unscoped.filter(employee=emp, status="active").count() == 1
    assert structure(c, emp, eff="2024-01-01").status_code == 400  # must start after current


def test_manager_cannot_approve_structure(world):
    emp = mem(world["cashier_a1"], world["a"])
    c = client_for(world["mgr_a1"], "alpha")
    sid = structure(c, emp).json()["data"]["id"]
    assert call(c, "post", f"{P}/structures/{sid}/approve/").status_code == 400


def test_reject_structure_needs_reason(world):
    emp = mem(world["cashier_a1"], world["a"])
    sid = structure(client_for(world["mgr_a1"], "alpha"), emp).json()["data"]["id"]
    admin = client_for(world["admin_a"], "alpha")
    assert call(admin, "post", f"{P}/structures/{sid}/reject/", {}).status_code == 400
    assert call(admin, "post", f"{P}/structures/{sid}/reject/", {"reason": "Too high"}).status_code == 200
    assert SalaryStructure.unscoped.get(pk=sid).status == "rejected"


def test_structure_change_emails_employee(world):
    activate(world, world["cashier_a1"])
    assert EmailLog.objects.filter(template="salary_structure_updated").exists()


# ---------------- scope / separation of duties ----------------
def test_manager_scope_and_rank(world):
    c = client_for(world["mgr_a1"], "alpha")
    assert structure(c, mem(world["cashier_a2"], world["a"])).status_code == 404  # other branch
    assert structure(c, mem(world["mgr_a1"], world["a"])).status_code == 400  # own pay
    assert structure(c, mem(world["mgr_a2"], world["a"])).status_code == 404  # peer in another branch
    assert structure(c, mem(world["admin_a"], world["a"])).status_code == 404  # admin not in manager's scope
    ids = {e["id"] for e in c.get(f"{P}/employees/").json()["data"]}
    assert mem(world["cashier_a1"], world["a"]).pk in ids and mem(world["cashier_a2"], world["a"]).pk not in ids
    assert mem(world["cust_a"], world["a"]).pk not in ids


def test_manager_cannot_manage_same_rank(world):
    peer = User.objects.create_user("peer@a.com", PW, full_name="peer", email_verified=True)
    pm = Membership.objects.create(user=peer, restaurant=world["a"], role=Role.MANAGER)
    pm.branches.set([world["a1"]])
    r = structure(client_for(world["mgr_a1"], "alpha"), pm)
    assert r.status_code == 400


def test_cashier_customer_anonymous_denied(world):
    for u in ("cashier_a1", "cust_a", "kitchen_a1"):
        c = client_for(world[u], "alpha")
        assert c.get(f"{P}/employees/").status_code == 403
        assert c.get(f"{P}/summary/").status_code == 403
        assert c.get(f"{P}/export.csv").status_code == 403
    from tests.conftest import TenantClient as APIClient
    assert APIClient(HTTP_HOST="alpha.platform.test").get(f"{P}/employees/").status_code in (401, 403)


def test_preparer_cannot_approve_own_record(world):
    emp, pid, rid = prepared(world, world["cashier_a1"])
    admin = client_for(world["admin_a"], "alpha")
    # admin prepares another, then cannot approve it (no opt-in)
    emp2 = activate(world, world["kitchen_a1"])
    r = call(admin, "post", f"{P}/periods/{pid}/records/", {"membership_id": emp2.pk})
    rid2 = r.json()["data"]["id"]
    call(admin, "post", f"{P}/records/{rid2}/submit/")
    assert call(admin, "post", f"{P}/records/{rid2}/approve/").status_code == 400
    # manager is not an approver at all
    call(client_for(world["mgr_a1"], "alpha"), "post", f"{P}/records/{rid}/submit/")
    assert call(client_for(world["mgr_a1"], "alpha"), "post", f"{P}/records/{rid}/approve/").status_code == 400


def test_admin_cannot_handle_own_pay_and_optin(world):
    admin = client_for(world["admin_a"], "alpha")
    me = mem(world["admin_a"], world["a"])
    assert structure(admin, me).status_code == 400
    assert call(admin, "patch", f"{P}/settings/", {"allow_admin_self_approval": "yes"}).status_code == 400
    assert call(admin, "patch", f"{P}/settings/", {"allow_admin_self_approval": True}).status_code == 200
    assert structure(admin, me).status_code == 201
    assert call(client_for(world["mgr_a1"], "alpha"), "get", f"{P}/settings/").status_code == 403


def test_admin_optin_allows_solo_flow(world):
    call(client_for(world["admin_a"], "alpha"), "patch", f"{P}/settings/", {"allow_admin_self_approval": True})
    admin = client_for(world["admin_a"], "alpha")
    emp = mem(world["cashier_a1"], world["a"])
    sid = structure(admin, emp).json()["data"]["id"]
    assert call(admin, "post", f"{P}/structures/{sid}/approve/").status_code == 200
    pid = call(admin, "post", f"{P}/periods/", {"year": 2024, "month": 5}).json()["data"]["id"]
    rid = call(admin, "post", f"{P}/periods/{pid}/records/", {"membership_id": emp.pk}).json()["data"]["id"]
    call(admin, "post", f"{P}/records/{rid}/submit/")
    assert call(admin, "post", f"{P}/records/{rid}/approve/").status_code == 200
    assert pay(admin, rid).status_code == 200


def test_approver_cannot_pay_own_approval(world):
    _, _, rid = approved(world, world["cashier_a1"])
    assert pay(client_for(world["admin_a"], "alpha"), rid).status_code == 400
    assert pay(client_for(world["mgr_a1"], "alpha"), rid).status_code == 200


# ---------------- workflow ----------------
def test_full_flow_receipt_and_employee_slip(world):
    emp, pid, rid = approved(world, world["cashier_a1"], adjustments=[{"type": "overtime", "name": "OT", "amount": "25.50"}])
    mgr = client_for(world["mgr_a1"], "alpha")
    r = pay(mgr, rid, method="bank_transfer", reference="TX123")
    assert r.status_code == 200, r.content
    d = r.json()["data"]
    assert d["status"] == "paid" and d["receipt_number"] == "SAL-000001" and d["net"] == "1025.50"
    assert EmailLog.objects.filter(template="salary_paid").count() == 1
    me = client_for(world["cashier_a1"], "alpha").get(f"{P}/me/").json()["data"]
    assert len(me["slips"]) == 1 and me["slips"][0]["net"] == "1025.50" and me["structure"]["basic_salary"] == "1000.00"
    pdf = client_for(world["cashier_a1"], "alpha").get(f"{P}/me/records/{rid}/pdf/")
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert mgr.get(f"{P}/records/{rid}/pdf/").status_code == 200


def test_employee_sees_only_own_and_customers_never(world):
    approved(world, world["cashier_a1"])
    other = client_for(world["kitchen_a1"], "alpha").get(f"{P}/me/").json()["data"]
    assert other["slips"] == [] and other["structure"] is None
    assert client_for(world["cust_a"], "alpha").get(f"{P}/me/").status_code == 400
    _, _, rid = approved(world, world["cashier_a1"], month=4) if False else (None, None, None)
    recs = PayrollRecord.unscoped.all()
    rid = recs.first().pk
    mgr = client_for(world["mgr_a1"], "alpha")
    pay(mgr, rid)
    assert client_for(world["kitchen_a1"], "alpha").get(f"{P}/me/records/{rid}/pdf/").status_code == 404
    assert client_for(world["cust_a"], "alpha").get(f"{P}/me/records/{rid}/pdf/").status_code == 400


def test_unpaid_slip_pdf_unavailable(world):
    _, _, rid = approved(world, world["cashier_a1"])
    assert client_for(world["cashier_a1"], "alpha").get(f"{P}/me/records/{rid}/pdf/").status_code == 404


def test_draft_not_visible_to_employee(world):
    prepared(world, world["cashier_a1"])
    assert client_for(world["cashier_a1"], "alpha").get(f"{P}/me/").json()["data"]["slips"] == []


def test_snapshot_immutable_after_structure_change(world):
    emp, pid, rid = approved(world, world["cashier_a1"])
    c = client_for(world["mgr_a1"], "alpha")
    sid = structure(c, emp, basic="9999.00", eff="2024-09-01").json()["data"]["id"]
    call(client_for(world["admin_a"], "alpha"), "post", f"{P}/structures/{sid}/approve/")
    assert c.get(f"{P}/records/{rid}/").json()["data"]["net"] == "1000.00"
    assert pay(c, rid).json()["data"]["net"] == "1000.00"


def test_paid_record_immutable(world):
    _, _, rid = approved(world, world["cashier_a1"])
    pay(client_for(world["mgr_a1"], "alpha"), rid)
    rec = PayrollRecord.unscoped.get(pk=rid)
    rec.net = Decimal("1.00")
    with pytest.raises(PermissionError):
        rec.save()
    with pytest.raises(PermissionError):
        rec.delete()
    receipt = SalaryReceipt.unscoped.get(record=rec)
    with pytest.raises(PermissionError):
        receipt.save()
    with pytest.raises(PermissionError):
        receipt.delete()


def test_cannot_edit_or_repay_finalised(world):
    emp, pid, rid = approved(world, world["cashier_a1"])
    mgr = client_for(world["mgr_a1"], "alpha")
    assert call(mgr, "post", f"{P}/periods/{pid}/records/", {"membership_id": emp.pk}).status_code == 400
    assert pay(mgr, rid).status_code == 200
    assert pay(mgr, rid).status_code == 400
    assert call(mgr, "post", f"{P}/records/{rid}/cancel/", {"reason": "x"}).status_code == 400


def test_must_submit_before_approve_and_pay(world):
    _, _, rid = prepared(world, world["cashier_a1"])
    assert call(client_for(world["admin_a"], "alpha"), "post", f"{P}/records/{rid}/approve/").status_code == 400
    assert pay(client_for(world["mgr_a1"], "alpha"), rid).status_code == 400


def test_reject_then_edit_resubmit(world):
    emp, pid, rid = prepared(world, world["cashier_a1"])
    mgr, admin = client_for(world["mgr_a1"], "alpha"), client_for(world["admin_a"], "alpha")
    call(mgr, "post", f"{P}/records/{rid}/submit/")
    assert call(admin, "post", f"{P}/records/{rid}/reject/", {}).status_code == 400
    assert call(admin, "post", f"{P}/records/{rid}/reject/", {"reason": "Wrong overtime"}).status_code == 200
    r = call(mgr, "post", f"{P}/periods/{pid}/records/", {"membership_id": emp.pk, "adjustments": [{"type": "overtime", "name": "OT", "amount": "10"}]})
    assert r.status_code == 201 and r.json()["data"]["net"] == "1010.00" and r.json()["data"]["status"] == "draft"


def test_payment_validation(world):
    _, _, rid = approved(world, world["cashier_a1"])
    mgr = client_for(world["mgr_a1"], "alpha")
    assert pay(mgr, rid, method="bank_transfer", reference="").status_code == 400
    assert pay(mgr, rid, paid_on=(TODAY + datetime.timedelta(days=2)).isoformat()).status_code == 400
    assert pay(mgr, rid, method="bitcoin").status_code == 400
    assert pay(mgr, rid).status_code == 200


def test_payment_idempotent(world):
    _, _, rid = approved(world, world["cashier_a1"])
    mgr = client_for(world["mgr_a1"], "alpha")
    k = uuid.uuid4().hex
    a, b = pay(mgr, rid, key=k), pay(mgr, rid, key=k)
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    assert SalaryReceipt.unscoped.count() == 1
    assert mgr.post(f"{P}/records/{rid}/pay/", {"method": "cash", "paid_on": TODAY.isoformat()}, format="json").status_code == 400  # key required


def test_receipt_numbers_sequential(world):
    for u in ("cashier_a1", "kitchen_a1"):
        _, _, rid = approved(world, world[u], month=3)
        pay(client_for(world["mgr_a1"], "alpha"), rid)
    assert sorted(SalaryReceipt.unscoped.values_list("number", flat=True)) == ["SAL-000001", "SAL-000002"]


def test_generate_period_scoped(world):
    activate(world, world["cashier_a1"])
    admin = client_for(world["admin_a"], "alpha")
    pid = call(admin, "post", f"{P}/periods/", {"year": 2024, "month": 6}).json()["data"]["id"]
    assert call(admin, "post", f"{P}/periods/", {"year": 2024, "month": 6}).status_code == 400  # duplicate
    r = call(admin, "post", f"{P}/periods/{pid}/generate/").json()["data"]
    assert r["created"] == 1
    assert call(admin, "post", f"{P}/periods/{pid}/generate/").json()["data"]["created"] == 0
    mgr = client_for(world["mgr_a1"], "alpha")
    assert len(mgr.get(f"{P}/periods/{pid}/").json()["data"]["records"]) == 1


def test_record_before_structure_effective_rejected(world):
    emp = activate(world, world["cashier_a1"], eff="2025-01-01")
    c = client_for(world["mgr_a1"], "alpha")
    pid = call(c, "post", f"{P}/periods/", {"year": 2024, "month": 3}).json()["data"]["id"]
    assert call(c, "post", f"{P}/periods/{pid}/records/", {"membership_id": emp.pk}).status_code == 400


# ---------------- tenancy ----------------
def test_cross_tenant_isolation(world):
    emp, pid, rid = approved(world, world["cashier_a1"])
    b = client_for(world["admin_b"], "bravo")
    assert b.get(f"{P}/records/{rid}/").status_code == 404
    assert call(b, "post", f"{P}/records/{rid}/approve/").status_code == 404
    assert b.get(f"{P}/periods/{pid}/").status_code == 404
    assert structure(b, emp).status_code == 404
    assert b.get(f"{P}/employees/").json()["data"] == [] or all(e["email"].endswith("@b.com") for e in b.get(f"{P}/employees/").json()["data"])
    # a user of tenant A cannot use tenant B's host
    assert client_for(world["admin_a"], "bravo").get(f"{P}/employees/").status_code in (401, 403, 404)


# ---------------- reports ----------------
def test_summary_and_csv_scope(world):
    _, _, rid = approved(world, world["cashier_a1"])
    pay(client_for(world["mgr_a1"], "alpha"), rid)
    emp2, _, rid2 = approved(world, world["cashier_a2"]) if False else (None, None, None)
    admin = client_for(world["admin_a"], "alpha")
    s = admin.get(f"{P}/summary/?year=2024&month=3").json()["data"]
    assert s["paid_net"] == "1000.00" and s["by_status"]["paid"]["count"] == 1
    csv = client_for(world["mgr_a1"], "alpha").get(f"{P}/export.csv?year=2024")
    assert csv.status_code == 200 and "SAL-000001" in csv.content.decode()
    assert client_for(world["mgr_a2"], "alpha").get(f"{P}/export.csv?year=2024").content.decode().count("SAL-000001") == 0
    assert client_for(world["admin_b"], "bravo").get(f"{P}/export.csv?year=2024").content.decode().count("SAL-000001") == 0
    assert client_for(world["mgr_a2"], "alpha").get(f"{P}/summary/?year=2024").json()["data"]["paid_net"] == "0.00"


def test_csv_formula_injection_neutralised(world):
    u = User.objects.create_user("evil@a.com", PW, full_name="=HYPERLINK(1)", email_verified=True)
    m = Membership.objects.create(user=u, restaurant=world["a"], role=Role.WAITER)
    m.branches.set([world["a1"]])
    activate(world, u)
    c = client_for(world["mgr_a1"], "alpha")
    pid = call(c, "post", f"{P}/periods/", {"year": 2024, "month": 8}).json()["data"]["id"]
    call(c, "post", f"{P}/periods/{pid}/records/", {"membership_id": m.pk})
    body = c.get(f"{P}/export.csv?year=2024").content.decode()
    assert ",=HYPERLINK" not in body and "'=HYPERLINK" in body


def test_money_never_float_in_responses(world):
    _, _, rid = prepared(world, world["cashier_a1"])
    d = client_for(world["mgr_a1"], "alpha").get(f"{P}/records/{rid}/").json()["data"]
    for k in ("basic_salary", "gross", "net", "total_deductions"):
        assert isinstance(d[k], str)


# ---------------- statutory tax and contribution rules (Phase 15) ----------------
from apps.payroll.services import apply_rules, clean_rules  # noqa: E402

PAYE = {"name": "Income tax", "kind": "brackets", "base": "taxable", "bearer": "employee",
        "brackets": [{"up_to": "500.00", "rate": "0"}, {"up_to": "1500.00", "rate": "10"}, {"up_to": None, "rate": "25"}]}
PENSION_EE = {"name": "Pension (employee)", "kind": "percent", "base": "basic", "rate": "5", "bearer": "employee", "pre_tax": True}
PENSION_ER = {"name": "Pension (employer)", "kind": "percent", "base": "basic", "rate": "10", "bearer": "employer"}


def test_progressive_brackets_and_pre_tax_contributions():
    from decimal import Decimal as D

    rules = clean_rules([PENSION_EE, PAYE, PENSION_ER])
    lines, emp, boss = apply_rules(rules, D("2000.00"), D("2000.00"))
    # pension 5% of 2000 = 100 (pre-tax); taxable = 1900; tax = 0 on 500 + 10% of 1000 + 25% of 400 = 100 + 100 = 200
    assert emp == D("300.00") and boss == D("200.00")
    by = {l["name"]: l["amount"] for l in lines}
    assert by["Pension (employee)"] == "100.00" and by["Income tax"] == "200.00" and by["Pension (employer)"] == "200.00"
    assert [l["type"] for l in lines].count("employer_contribution") == 1


def test_bracket_edges_and_zero():
    from decimal import Decimal as D

    rule = clean_rules([PAYE])[0]
    from apps.payroll.services import _rule_amount
    assert _rule_amount(rule, D("0.00")) == D("0.00") and _rule_amount(rule, D("500.00")) == D("0.00")
    assert _rule_amount(rule, D("1500.00")) == D("100.00") and _rule_amount(rule, D("1500.01")) == D("100.00")  # 0.01 x 25% = 0.0025 rounds to 0
    assert _rule_amount(rule, D("1600.00")) == D("125.00")


def test_invalid_rules_are_rejected():
    from rest_framework.exceptions import ValidationError
    bad = [
        [{"name": "x", "kind": "percent", "rate": "101"}], [{"name": "", "kind": "percent", "rate": "5"}], [{"name": "x", "kind": "weird"}],
        [{"name": "x", "kind": "brackets", "brackets": []}], [{"name": "x", "kind": "brackets", "brackets": [{"up_to": "100", "rate": "5"}]}],
        [{"name": "x", "kind": "brackets", "brackets": [{"up_to": "200", "rate": "5"}, {"up_to": "100", "rate": "5"}, {"up_to": None, "rate": "9"}]}],
        [{"name": "x", "kind": "brackets", "brackets": [{"up_to": None, "rate": "5"}, {"up_to": None, "rate": "9"}]}],
        [{"name": "x", "kind": "percent", "rate": "5", "base": "taxable", "bearer": "employer"}], "nope", [PENSION_EE] * 11,
    ]
    for b in bad:
        with pytest.raises(ValidationError):
            clean_rules(b)


def test_rules_flow_into_records_receipts_and_reports(world):
    admin = client_for(world["admin_a"], "alpha")
    assert call(client_for(world["mgr_a1"], "alpha"), "patch", f"{P}/settings/", {"tax_rules": [PAYE]}).status_code == 403
    r = call(admin, "patch", f"{P}/settings/", {"tax_rules": [PENSION_EE, PAYE, PENSION_ER]})
    assert r.status_code == 200 and len(r.json()["data"]["tax_rules"]) == 3
    assert call(admin, "patch", f"{P}/settings/", {"tax_rules": [{"name": "x", "kind": "percent", "rate": "500"}]}).status_code == 400
    emp = activate(world, world["cashier_a1"], basic="2000.00")
    c = client_for(world["mgr_a1"], "alpha")
    pid = call(c, "post", f"{P}/periods/", {"year": 2024, "month": 3}).json()["data"]["id"]
    rec = call(c, "post", f"{P}/periods/{pid}/records/", {"membership_id": emp.pk}).json()["data"]
    assert rec["gross"] == "2000.00" and rec["total_statutory"] == "300.00" and rec["total_deductions"] == "300.00" and rec["net"] == "1700.00"
    assert rec["employer_contributions"] == "200.00"
    assert {l["name"] for l in rec["lines"]} >= {"Income tax", "Pension (employee)", "Pension (employer)"}
    # changing the rules afterwards never alters a prepared record
    call(admin, "patch", f"{P}/settings/", {"tax_rules": []})
    assert c.get(f"{P}/records/{rec['id']}/").json()["data"]["net"] == "1700.00"
    call(c, "post", f"{P}/records/{rec['id']}/submit/")
    call(admin, "post", f"{P}/records/{rec['id']}/approve/")
    assert pay(c, rec["id"]).status_code == 200
    d = admin.get("/api/v1/reports/finance/", {"from": (TODAY - datetime.timedelta(days=30)).isoformat(), "to": TODAY.isoformat()}).json()["data"]["expenses"]
    assert d["payroll_paid"] == "1700.00" and d["statutory_withheld"] == "300.00" and d["employer_contributions"] == "200.00" and d["payroll_cost"] == "2200.00"
    pdf = client_for(world["cashier_a1"], "alpha").get(f"{P}/me/records/{rec['id']}/pdf/")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_rules_that_exceed_gross_are_rejected(world):
    admin = client_for(world["admin_a"], "alpha")
    call(admin, "patch", f"{P}/settings/", {"tax_rules": [{"name": "Huge", "kind": "percent", "base": "gross", "rate": "100", "bearer": "employee"}]})
    emp = activate(world, world["cashier_a1"])
    c = client_for(world["mgr_a1"], "alpha")
    pid = call(c, "post", f"{P}/periods/", {"year": 2024, "month": 3}).json()["data"]["id"]
    ok = call(c, "post", f"{P}/periods/{pid}/records/", {"membership_id": emp.pk})
    assert ok.status_code == 201 and ok.json()["data"]["net"] == "0.00"  # 100% leaves zero, never negative
    r = call(c, "post", f"{P}/periods/{pid}/records/", {"membership_id": emp.pk, "adjustments": [{"type": "deduction", "name": "More", "amount": "1"}]})
    assert r.status_code == 400
