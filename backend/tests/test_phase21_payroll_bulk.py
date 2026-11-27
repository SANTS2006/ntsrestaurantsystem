"""Payroll notifications (in the app and by email), bulk actions on many employees, and generated payment references."""
import re
import uuid

import pytest

from apps.notifications.models import Notification
from apps.notifications.providers import ConsoleProvider
from apps.payroll.models import PayrollRecord, SalaryReceipt
from tests.conftest import client_for
from tests.test_phase11_payroll import P, TODAY, activate, approved, call, mem, pay, prepared

STAFF = ("cashier_a1", "kitchen_a1", "delivery_a1")


@pytest.fixture(autouse=True)
def clean_outbox():
    ConsoleProvider.outbox.clear()


def month(world, users=STAFF):
    for u in users:
        activate(world, world[u])
    mgr = client_for(world["mgr_a1"], "alpha")
    return call(mgr, "post", f"{P}/periods/", {"year": 2024, "month": 3}).json()["data"]["id"]


def bulk(user, pid, action, ids, key=None, **extra):
    return client_for(user, "alpha").post(f"{P}/periods/{pid}/bulk/", {"action": action, "record_ids": ids, **extra}, format="json",
                                          HTTP_IDEMPOTENCY_KEY=key or uuid.uuid4().hex)


def told(email):
    return [n.title for n in Notification.objects.filter(user__email=email).order_by("-id")]


def mails(email):
    return [m["subject"] for m in ConsoleProvider.outbox if m["to"] == email]


def test_salary_change_notifies_admin_and_employee_in_app_and_by_email(world, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        activate(world, world["cashier_a1"])
    assert {"A salary is waiting for your approval", "Salary change approved"} <= set(told("admin@a.com"))
    assert {"A salary change was sent for approval", "Your salary change was approved"} <= set(told("cash1@a.com"))
    assert "Salary change approved" in told("mgr1@a.com")  # who proposed it hears the decision
    assert any("waiting for your approval" in s for s in mails("admin@a.com"))
    assert any("sent for approval" in s for s in mails("cash1@a.com"))
    assert not told("admin@b.com") and not told("kitchen1@a.com")


def test_rejection_reason_reaches_the_team_but_never_the_employee(world, django_capture_on_commit_callbacks):
    _, _, rid = prepared(world, world["cashier_a1"])
    call(client_for(world["mgr_a1"], "alpha"), "post", f"{P}/records/{rid}/submit/")
    ConsoleProvider.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        call(client_for(world["admin_a"], "alpha"), "post", f"{P}/records/{rid}/reject/", {"reason": "SECRET wrong overtime"})
    assert "Payroll rejected" in told("mgr1@a.com") and "Your pay is being reviewed" in told("cash1@a.com")
    assert not any("SECRET" in m["html"] for m in ConsoleProvider.outbox if m["to"] == "cash1@a.com")
    assert any("SECRET" in m["html"] for m in ConsoleProvider.outbox if m["to"] == "mgr1@a.com")
    assert not Notification.objects.filter(user__email="cash1@a.com", body__contains="SECRET").exists()


def test_candidates_and_generating_for_selected_employees(world):
    pid = month(world, ("cashier_a1", "kitchen_a1"))
    mgr = client_for(world["mgr_a1"], "alpha")
    people = {c["email"]: c for c in mgr.get(f"{P}/periods/{pid}/candidates/").json()["data"]}
    assert people["cash1@a.com"]["eligible"] and not people["deliv1@a.com"]["eligible"] and "approved salary" in people["deliv1@a.com"]["reason"]
    assert "cash2@a.com" not in people  # another branch
    chosen = [mem(world["cashier_a1"], world["a"]).pk, mem(world["delivery_a1"], world["a"]).pk, 999999]
    r = call(mgr, "post", f"{P}/periods/{pid}/generate/", {"membership_ids": chosen}).json()["data"]
    assert r["created"] == 1 and r["skipped"] == 2 and PayrollRecord.unscoped.count() == 1
    again = call(mgr, "post", f"{P}/periods/{pid}/generate/", {}).json()["data"]
    assert again["created"] == 1 and PayrollRecord.unscoped.count() == 2  # the rest of those who are due, nobody twice


def test_bulk_submit_approve_pay_with_one_summary_and_generated_references(world, django_capture_on_commit_callbacks):
    pid = month(world)
    mgr = client_for(world["mgr_a1"], "alpha")
    Notification.objects.all().delete()
    ConsoleProvider.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        assert call(mgr, "post", f"{P}/periods/{pid}/generate/", {}).json()["data"]["created"] == 3
        ids = list(PayrollRecord.unscoped.values_list("pk", flat=True))
        r = bulk(world["mgr_a1"], pid, "submit", ids)
    assert r.status_code == 200 and len(r.json()["data"]["done"]) == 3, r.content
    assert told("admin@a.com") == ["Payroll waiting for your approval", "Payroll drafts generated"]  # one each, not one per employee
    assert "3 employees" in Notification.objects.get(user__email="admin@a.com", title="Payroll waiting for your approval").body
    assert mails("admin@a.com").count("Payroll waiting for your approval (Alpha)") == 1
    assert told("cash1@a.com") == ["Your pay was sent for approval", "Your pay is being prepared"]
    assert "1000" not in " ".join(Notification.objects.filter(user__email="cash1@a.com").values_list("body", flat=True))

    assert len(bulk(world["admin_a"], pid, "approve", ids).json()["data"]["done"]) == 3
    with django_capture_on_commit_callbacks(execute=True):
        paid = bulk(world["mgr_a1"], pid, "pay", ids, method="bank_transfer", paid_on=TODAY.isoformat())
    data = paid.json()["data"]
    assert len(data["done"]) == 3 and not data["failed"], paid.content
    refs = [d["reference"] for d in data["done"]]
    assert len(set(refs)) == 3 and all(re.fullmatch(r"PAY-202403-\d{6}", x) for x in refs)
    assert SalaryReceipt.unscoped.count() == 3
    assert told("admin@a.com").count("Salaries paid") == 1 and "Your salary has been paid" in told("kitchen1@a.com")
    assert any(s.startswith("Salary paid") for s in mails("kitchen1@a.com"))
    assert any("Salaries paid" in s for s in mails("admin@a.com"))


def test_bulk_keeps_every_single_record_rule(world):
    pid = month(world, ("cashier_a1", "kitchen_a1"))
    mgr = client_for(world["mgr_a1"], "alpha")
    call(mgr, "post", f"{P}/periods/{pid}/generate/", {})
    first, second = PayrollRecord.unscoped.order_by("pk").values_list("pk", flat=True)
    call(mgr, "post", f"{P}/records/{first}/submit/")
    mixed = bulk(world["admin_a"], pid, "approve", [first, second, 424242, first]).json()["data"]
    assert [d["id"] for d in mixed["done"]] == [first]
    assert {f["id"] for f in mixed["failed"]} == {second, 424242}
    assert "submitted" in next(f for f in mixed["failed"] if f["id"] == second)["reason"]
    assert not bulk(world["mgr_a1"], pid, "approve", [second]).json()["data"]["done"]  # only the administrator approves
    own = bulk(world["admin_a"], pid, "pay", [first], method="cash", paid_on=TODAY.isoformat()).json()["data"]
    assert not own["done"] and "different person" in own["failed"][0]["reason"]


def test_bulk_pay_is_idempotent_and_validated(world):
    pid = month(world, ("cashier_a1",))
    mgr = client_for(world["mgr_a1"], "alpha")
    call(mgr, "post", f"{P}/periods/{pid}/generate/", {})
    rid = PayrollRecord.unscoped.get().pk
    bulk(world["mgr_a1"], pid, "submit", [rid])
    bulk(world["admin_a"], pid, "approve", [rid])
    assert bulk(world["mgr_a1"], pid, "pay", [rid]).status_code == 400  # method and date required
    assert bulk(world["mgr_a1"], pid, "reject", [rid]).status_code == 400  # reason required
    assert bulk(world["mgr_a1"], pid, "pay", [], method="cash", paid_on=TODAY.isoformat()).status_code == 400
    key = uuid.uuid4().hex
    a = bulk(world["mgr_a1"], pid, "pay", [rid], key=key, method="cash", paid_on=TODAY.isoformat())
    b = bulk(world["mgr_a1"], pid, "pay", [rid], key=key, method="cash", paid_on=TODAY.isoformat())
    assert a.json() == b.json() and SalaryReceipt.unscoped.count() == 1
    assert mgr.post(f"{P}/periods/{pid}/bulk/", {"action": "submit", "record_ids": [rid]}, format="json").status_code == 400  # key required


def test_bulk_is_closed_to_other_restaurants_and_roles(world):
    pid = month(world, ("cashier_a1",))
    for user in (world["cashier_a1"], world["cust_a"], world["admin_b"]):
        assert bulk(user, pid, "submit", [1]).status_code == 403
    assert client_for(world["admin_b"], "bravo").get(f"{P}/periods/{pid}/candidates/").status_code == 404


def test_single_payment_generates_a_reference_and_keeps_a_given_one(world):
    _, _, rid = approved(world, world["cashier_a1"])
    r = pay(client_for(world["mgr_a1"], "alpha"), rid, method="bank_transfer", reference="")
    assert r.status_code == 200 and re.fullmatch(r"PAY-202403-\d{6}", r.json()["data"]["payment_reference"])
    _, _, other = approved(world, world["kitchen_a1"])
    r = pay(client_for(world["mgr_a1"], "alpha"), other, method="bank_transfer", reference="BANK-778")
    assert r.json()["data"]["payment_reference"] == "BANK-778"


def test_pay_notification_details_show_only_what_the_reader_may_see(world):
    _, _, rid = prepared(world, world["cashier_a1"])
    call(client_for(world["mgr_a1"], "alpha"), "post", f"{P}/records/{rid}/submit/")

    def details(user, title):
        n = Notification.objects.filter(user=user, title=title).latest("id")
        return client_for(user, "alpha").get(f"/api/v1/notifications/{n.pk}/").json()["data"]["details"]

    mine = details(world["cashier_a1"], "Your pay was sent for approval")
    assert mine["heading"].endswith("2024-03") and not any(f["label"] == "Net pay" for f in mine["fields"])
    boss = details(world["admin_a"], "Payroll waiting for your approval")
    assert any(f["label"] == "Net pay" for f in boss["fields"])


def test_without_a_queue_server_mail_is_handed_to_a_background_thread(world, settings, monkeypatch, django_capture_on_commit_callbacks):
    from apps.notifications import services
    from apps.notifications.models import EmailLog

    settings.EMAIL_IN_BACKGROUND = True
    waiting = []
    monkeypatch.setattr(services._sender, "submit", lambda fn, *args: waiting.append((fn, args)))
    with django_capture_on_commit_callbacks(execute=True):
        services.queue_email("password_changed", "later@x.com", {"name": "L"})
    assert len(waiting) == 1 and not mails("later@x.com")  # the request did not wait for the mail service
    fn, args = waiting[0]
    monkeypatch.setattr(services, "close_old_connections", lambda: None)  # the test keeps its own connection
    fn(*args)
    assert mails("later@x.com") and EmailLog.objects.get(to_email="later@x.com").status == "sent"
