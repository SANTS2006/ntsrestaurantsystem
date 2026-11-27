"""Who hears what about pay, in the app and by email.

* Restaurant administrators hear about everything that needs or received a decision (one summary, however many records).
* Whoever prepared the pay hears what happened to it.
* Every employee hears about their own pay at each step, and nothing about anyone else's. Amounts are only told once the pay is
  approved; the reason for a rejection or cancellation is internal and is never sent to the employee.

A problem while telling people never undoes the payroll action itself.
"""
import logging

from django.db import transaction

from apps.accounts.models import Role, User
from apps.notifications.inapp import notify_users
from apps.notifications.services import queue_email

log = logging.getLogger(__name__)
MY_PAY = "/manage/my-pay"
RUNS = "/manage/payroll?tab=runs"
SALARIES = "/manage/payroll?tab=employees"
MAX_LINES = 25

# event -> (heading for the team, heading for the employee, sentence for the employee)
RECORD_EVENTS = {
    "generated": ("Payroll drafts generated", "Your pay is being prepared", "Your pay for {period} is being prepared."),
    "submitted": ("Payroll waiting for your approval", "Your pay was sent for approval", "Your pay for {period} was sent to the administrator for approval."),
    "approved": ("Payroll approved", "Your pay was approved", "Your pay for {period} was approved. Net pay: {net}. You will be told when it is paid."),
    "rejected": ("Payroll rejected", "Your pay is being reviewed", "Your pay for {period} was sent back for correction. You will be told when it is sent for approval again."),
    "cancelled": ("Payroll cancelled", "A pay record was cancelled", "Your pay record for {period} was cancelled. Ask your manager if you have a question."),
    "paid": ("Salaries paid", "Your salary has been paid", "Your salary for {period} was paid. Net pay: {net}. Receipt {receipt}, reference {reference}."),
}
EMAIL_EMPLOYEE = {"submitted", "approved", "rejected", "cancelled"}  # "paid" has its own receipt email; drafts are in-app only
EMAIL_TEAM = {"generated", "submitted", "approved", "rejected", "cancelled", "paid"}


def admins_of(restaurant):
    return list(User.objects.filter(memberships__restaurant=restaurant, memberships__is_active=True,
                                    memberships__role=Role.RESTAURANT_ADMIN, is_active=True).distinct())


def _name(user):
    return user.full_name or user.email


def _safely(fn):
    try:
        with transaction.atomic():
            fn()
    except Exception:  # noqa: BLE001
        log.exception("could not send a payroll notification")


def _tell(restaurant, users, kind, title, body, path, about, *, email_key=None, lines=None, note=None):
    notify_users(users, kind, title, body, path, restaurant, about=about)
    if not email_key:
        return
    for user in users:
        queue_email("payroll_update", user.email,
                    {"name": user.full_name, "subject": title, "heading": title, "text": body, "lines": lines or [], "note": note or "",
                     "url": restaurant.public_url + path},
                    restaurant=restaurant, dedupe_key=f"{email_key}:{user.pk}")


def _stamp(obj):
    return f"{obj.pk}:{obj.updated_at.timestamp()}"


def records(request, event, items, reason=""):
    """Announce one step (`event`) taken on one or many payroll records."""
    items = list(items)
    if not items:
        return
    _safely(lambda: _records(request, event, items, reason))


def _records(request, event, items, reason):
    tenant, actor = request.tenant, request.user
    team_title, own_title, own_text = RECORD_EVENTS[event]
    first, n = items[0], len(items)
    currency = first.currency
    total = sum(r.net for r in items)
    periods = ", ".join(sorted({str(r.period) for r in items}))
    who = _name(first.employee.user) if n == 1 else f"{n} employees"
    body = f"{who}, {periods}. Total net pay {currency} {total}. By {_name(actor)}."
    lines = [f"{_name(r.employee.user)}: {r.currency} {r.net}" for r in items[:MAX_LINES]]
    if n > MAX_LINES:
        lines.append(f"... and {n - MAX_LINES} more")
    path = f"{RUNS}&period={first.period_id}"
    about = ("payroll_record", first.pk) if n == 1 else None
    team = {u.pk: u for u in admins_of(tenant)}
    if event in ("approved", "rejected", "cancelled", "paid"):  # whoever prepared or approved it follows what happened
        ids = {r.prepared_by_id for r in items} | ({r.approved_by_id for r in items} if event in ("paid", "cancelled") else set())
        for user in User.objects.filter(pk__in=[i for i in ids if i], is_active=True,
                                        memberships__restaurant=tenant, memberships__is_active=True):
            team[user.pk] = user
    batch = f"payroll:{event}:{n}:{_stamp(first)}"
    _tell(tenant, list(team.values()), "payroll", team_title, body, path, about,
          email_key=f"team:{batch}" if event in EMAIL_TEAM else None, lines=lines,
          note=f"Reason: {reason}" if reason else "")

    for r in items:
        values = {"period": str(r.period), "net": f"{r.currency} {r.net}",
                  "receipt": r.receipt.number if event == "paid" else "", "reference": r.payment_reference}
        _tell(tenant, [r.employee.user], "salary", own_title, own_text.format(**values), MY_PAY, ("payroll_record", r.pk),
              email_key=f"own:{event}:{_stamp(r)}" if event in EMAIL_EMPLOYEE else None)


STRUCTURE_EVENTS = {
    "submitted": ("A salary is waiting for your approval", "A salary change was sent for approval",
                  "A change to your salary, starting {start}, was sent to the administrator for approval."),
    "approved": ("Salary change approved", "Your salary change was approved",
                 "Your new salary, starting {start}, was approved. You can see it under My pay."),
    "rejected": ("Salary change rejected", "Your salary change was not approved",
                 "The change to your salary that was to start {start} was not approved. Your current salary stays as it is."),
}


def structure(request, event, s, reason=""):
    """Announce a step of a salary change (set, approved or rejected)."""
    def run():
        tenant, actor = request.tenant, request.user
        team_title, own_title, own_text = STRUCTURE_EVENTS[event]
        employee = s.employee.user
        body = f"{_name(employee)}: basic salary {s.currency} {s.basic_salary} from {s.effective_from}. By {_name(actor)}."
        team = {u.pk: u for u in admins_of(tenant)}
        if event != "submitted" and s.created_by_id and s.created_by.is_active:
            team[s.created_by_id] = s.created_by
        about = ("salary_change", s.pk)
        _tell(tenant, list(team.values()), "payroll", team_title, body, SALARIES, about,
              email_key=f"team:salary:{event}:{s.pk}", note=f"Reason: {reason}" if reason else "")
        # an approval already has its own "salary details updated" email
        _tell(tenant, [employee], "salary", own_title, own_text.format(start=s.effective_from), MY_PAY, about,
              email_key=None if event == "approved" else f"own:salary:{event}:{s.pk}")
    _safely(run)
