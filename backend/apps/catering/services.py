"""Catering workflow. Every state change happens under a row lock, is recorded (history, audit) and may notify the customer."""
import hashlib
import secrets
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound

from apps.accounts.models import Membership, Role
from apps.catalog.models import Service
from apps.core.models import audit
from apps.notifications.services import queue_email
from apps.qrmenu.realtime import notify_branch
from apps.qrmenu.services import client_hash
from apps.tenants.models import Branch

from .models import (CateringNote, CateringPayment, CateringRequest, CateringSequence, CateringStatusHistory, Quotation,
                     Status)

S = Status
CENT = Decimal("0.01")

# Legal moves. quotation_sent / accepted are reached only through the quotation actions, never by a plain status change.
TRANSITIONS = {
    S.NEW: {S.UNDER_REVIEW, S.REJECTED, S.CANCELLED},
    S.UNDER_REVIEW: {S.QUOTATION_SENT, S.REJECTED, S.CANCELLED},
    S.QUOTATION_SENT: {S.ACCEPTED, S.UNDER_REVIEW, S.REJECTED, S.CANCELLED},
    S.ACCEPTED: {S.IN_PROGRESS, S.CANCELLED},
    S.IN_PROGRESS: {S.COMPLETED, S.CANCELLED},
    S.COMPLETED: set(), S.REJECTED: set(), S.CANCELLED: set(),
}
MANUAL_TARGETS = {S.UNDER_REVIEW, S.REJECTED, S.IN_PROGRESS, S.COMPLETED, S.CANCELLED}
NEEDS_REASON = {S.REJECTED, S.CANCELLED}
PAYMENT_METHODS = ("cash", "mobile_money", "bank_transfer", "other")
STAFF_ROLES = [Role.RESTAURANT_ADMIN, Role.MANAGER, Role.CASHIER, Role.KITCHEN, Role.WAITER, Role.WAITRESS, Role.DELIVERY]


def m(x) -> Decimal:
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def _hash(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def label(s):
    return Status(s).label


def _history(req, frm, to, actor, note=""):
    CateringStatusHistory.objects.create(restaurant=req.restaurant, request=req, from_status=frm, to_status=to, actor=actor, note=note[:300])


def _tell_customer(req, template, extra=None, dedupe=None):
    ctx = {"name": req.customer_name, "reference": req.reference, **(extra or {})}
    queue_email(template, req.customer_email, ctx, restaurant=req.restaurant, dedupe_key=dedupe)


def balance(req):
    accepted = req.quotations.filter(status=Quotation.QStatus.ACCEPTED).first()
    total = accepted.total if accepted else Decimal("0.00")
    paid = Decimal("0.00")
    for p in req.payments.all():
        paid += -p.amount if p.kind == CateringPayment.Kind.REFUND else p.amount
    return {"agreed_total": m(total), "paid": m(paid), "balance": m(total - paid), "currency": req.currency}


# ---- public submission -------------------------------------------------------------------------------
@transaction.atomic
def submit_public(request, data):
    tenant = request.tenant
    if tenant is None:
        raise NotFound()
    branch = None
    if data.get("branch_id"):
        branch = Branch.unscoped.filter(pk=data["branch_id"], restaurant=tenant, status="active").first()
        if branch is None:
            raise serializers.ValidationError({"branch_id": "Choose a valid branch."})
    ids = set(data.get("service_ids", []))
    services = list(Service.unscoped.filter(restaurant=tenant, is_active=True, pk__in=ids))
    if len(services) != len(ids):
        raise serializers.ValidationError({"service_ids": "One or more services are not available."})
    seq, _ = CateringSequence.objects.select_for_update().get_or_create(restaurant=tenant)
    seq.last_number += 1
    seq.save(update_fields=["last_number"])
    req = CateringRequest.objects.create(
        restaurant=tenant, branch=branch, reference=f"CAT-{seq.last_number:06d}", customer_name=data["customer_name"].strip(),
        customer_email=data["customer_email"].lower(), customer_phone=data["customer_phone"].strip(), event_type=data["event_type"],
        event_date=data["event_date"], event_location=data["event_location"].strip(), guests=data["guests"],
        food_preferences=data["food_preferences"].strip(), budget=data.get("budget"), currency=tenant.get_settings().currency,
        requirements=data["requirements"].strip(), consent_at=timezone.now(), client_hash=client_hash(request))
    req.services.set(services)
    _history(req, "", S.NEW, None, "Request received")
    audit("catering.request_created", restaurant=tenant, obj=req, metadata={"reference": req.reference}, request=request)
    _tell_customer(req, "catering_received", {"event": req.get_event_type_display(), "date": req.event_date.isoformat()}, f"catering:{req.pk}:received")
    if tenant.contact_email:  # alert the restaurant (never includes the customer's contact details)
        queue_email("catering_staff_alert", tenant.contact_email, {"reference": req.reference, "event": req.get_event_type_display(),
                    "date": req.event_date.isoformat(), "guests": req.guests, "url": f"{tenant.public_url}/manage/catering"},
                    restaurant=tenant, dedupe_key=f"catering:{req.pk}:staff")
    if branch:
        notify_branch(tenant.pk, branch.pk, {"type": "catering.request.created", "id": req.pk, "reference": req.reference, "branch_id": branch.pk})
        from apps.notifications import inapp

        inapp.notify_staff(tenant, branch.pk, ("restaurant_admin", "manager"), "catering", f"New catering request {req.reference}", req.get_event_type_display(), "/manage/catering")
    return req


# ---- status ----------------------------------------------------------------------------------------------
def _void_sent_quotes(req, note):
    for q in req.quotations.filter(status=Quotation.QStatus.SENT):
        q.status, q.token_hash, q.response_note = Quotation.QStatus.SUPERSEDED, None, note[:300]  # the emailed link stops working
        q.save()


def _move(req, to, actor, note="", notify=True):
    frm = req.status
    if to not in TRANSITIONS.get(frm, set()):
        raise serializers.ValidationError({"status": f"A request that is “{label(frm)}” cannot become “{label(to)}”."})
    if frm == S.QUOTATION_SENT and to != S.ACCEPTED:
        _void_sent_quotes(req, f"Withdrawn ({label(to)})")
    req.status = to
    if to in NEEDS_REASON:
        req.cancel_reason = note[:300]
    req.save()
    _history(req, frm, to, actor, note)
    audit("catering.status_changed", actor=actor, restaurant=req.restaurant, obj=req, metadata={"from": frm, "to": to})
    if notify and to in (S.UNDER_REVIEW, S.REJECTED, S.IN_PROGRESS, S.COMPLETED, S.CANCELLED):
        _tell_customer(req, "catering_status", {"status": label(to), "note": note if to in NEEDS_REASON else ""}, f"catering:{req.pk}:status:{to}:{frm}")


def lock(request_id, tenant, qs):
    req = qs.select_for_update().select_related("restaurant", "branch").filter(pk=request_id, restaurant=tenant).first()
    if req is None:
        raise NotFound()
    return req


@transaction.atomic
def change_status(request, request_id, to, note, qs):
    req = lock(request_id, request.tenant, qs)
    if to not in MANUAL_TARGETS:
        raise serializers.ValidationError({"status": "Use the quotation actions to send or accept a quotation."})
    if to in NEEDS_REASON and not note.strip():
        raise serializers.ValidationError({"note": "Please give a reason."})
    _move(req, to, request.user, note)
    return req


# ---- assignment, notes, contact ---------------------------------------------------------------------------
@transaction.atomic
def assign(request, request_id, user_id, qs):
    req = lock(request_id, request.tenant, qs)
    if user_id is None:
        req.assigned_to = None
        who = "nobody"
    else:
        mem = Membership.objects.filter(user_id=user_id, restaurant=request.tenant, is_active=True, role__in=STAFF_ROLES).select_related("user").first()
        if mem is None:
            raise serializers.ValidationError({"user_id": "Choose an active staff member of this restaurant."})
        if req.branch_id and mem.role != Role.RESTAURANT_ADMIN and not mem.branches.filter(pk=req.branch_id).exists():
            raise serializers.ValidationError({"user_id": "That person does not work at this request's branch."})
        req.assigned_to = mem.user
        who = mem.user.full_name or mem.user.email
    req.save(update_fields=["assigned_to", "updated_at"])
    CateringNote.objects.create(restaurant=req.restaurant, request=req, author=request.user, text=f"Assigned to {who}.")
    audit("catering.assigned", actor=request.user, restaurant=req.restaurant, obj=req, metadata={"user_id": user_id}, request=request)
    return req


@transaction.atomic
def set_branch(request, request_id, branch_id, qs):
    req = lock(request_id, request.tenant, qs)
    branch = Branch.unscoped.filter(pk=branch_id, restaurant=request.tenant, status="active").first() if branch_id else None
    if branch_id and branch is None:
        raise serializers.ValidationError({"branch_id": "Choose an active branch."})
    req.branch, req.assigned_to = branch, (req.assigned_to if branch and req.assigned_to and Membership.objects.filter(
        user=req.assigned_to, restaurant=request.tenant, branches=branch).exists() else None)
    req.save(update_fields=["branch", "assigned_to", "updated_at"])
    audit("catering.branch_set", actor=request.user, restaurant=req.restaurant, obj=req, metadata={"branch_id": branch_id}, request=request)
    return req


@transaction.atomic
def add_note(request, request_id, text, qs):
    req = lock(request_id, request.tenant, qs)
    return CateringNote.objects.create(restaurant=req.restaurant, request=req, author=request.user, text=text)


def contact_customer(request, request_id, subject, message, qs):
    with transaction.atomic():
        req = lock(request_id, request.tenant, qs)
        key = f"catering-contact:{req.pk}"
        sent = cache.get(key, 0)
        if sent >= 10:
            raise serializers.ValidationError({"detail": "Too many messages sent for this request in the last hour."})
        cache.set(key, sent + 1, 3600)
        _tell_customer(req, "catering_message", {"subject": subject, "message": message})
        CateringNote.objects.create(restaurant=req.restaurant, request=req, author=request.user, kind="email", text=f"Emailed the customer: {subject}\n\n{message}"[:3000])
        audit("catering.customer_contacted", actor=request.user, restaurant=req.restaurant, obj=req, request=request)
    return req


# ---- quotations ---------------------------------------------------------------------------------------------------
def price_items(items, discount, tax_rate):
    lines, subtotal = [], Decimal("0")
    for i in items:
        qty, unit = Decimal(i["quantity"]), Decimal(i["unit_price"])  # shown in plain notation below: 120, 2.5 (never 1.2E+2)
        line = m(qty * unit)
        lines.append({"description": i["description"].strip(), "quantity": format(qty.normalize(), "f"), "unit_price": str(m(unit)), "line_total": str(line)})
        subtotal += line
    discount = m(discount)
    if discount > subtotal:
        raise serializers.ValidationError({"discount": "The discount cannot be more than the subtotal."})
    tax = m((subtotal - discount) * Decimal(tax_rate) / Decimal(100))
    return lines, m(subtotal), discount, tax, m(subtotal - discount + tax)


@transaction.atomic
def create_quotation(request, request_id, data, qs):
    req = lock(request_id, request.tenant, qs)
    if req.status not in (S.NEW, S.UNDER_REVIEW, S.QUOTATION_SENT):
        raise serializers.ValidationError({"detail": "A quotation cannot be created for this request."})
    today = timezone.now().date()
    if not (today <= data["valid_until"] <= today + timedelta(days=365)):
        raise serializers.ValidationError({"valid_until": "Choose a date within the next year."})
    rate = req.restaurant.get_settings().tax_rate_percent
    lines, subtotal, discount, tax, total = price_items(data["items"], data["discount"], rate)
    version = (req.quotations.order_by("-version").values_list("version", flat=True).first() or 0) + 1
    q = Quotation.objects.create(restaurant=req.restaurant, request=req, version=version, items=lines, subtotal=subtotal, discount=discount,
                                 tax_rate_percent=rate, tax_total=tax, total=total, currency=req.currency, valid_until=data["valid_until"],
                                 terms=data["terms"], created_by=request.user)
    audit("catering.quotation_created", actor=request.user, restaurant=req.restaurant, obj=q, metadata={"total": str(total)}, request=request)
    return q


@transaction.atomic
def send_quotation(request, request_id, quotation_id, qs):
    req = lock(request_id, request.tenant, qs)
    q = Quotation.objects.select_for_update().filter(pk=quotation_id, request=req).first()
    if q is None:
        raise NotFound()
    if q.status != Quotation.QStatus.DRAFT:
        raise serializers.ValidationError({"detail": "Only a draft quotation can be sent."})
    if q.valid_until < timezone.now().date():
        raise serializers.ValidationError({"valid_until": "This quotation has already expired. Create a new one."})
    if req.status not in (S.NEW, S.UNDER_REVIEW, S.QUOTATION_SENT):
        raise serializers.ValidationError({"detail": "This request can no longer receive a quotation."})
    if req.status == S.NEW:
        _move(req, S.UNDER_REVIEW, request.user, "Quotation prepared", notify=False)
    for old in req.quotations.filter(status=Quotation.QStatus.SENT).exclude(pk=q.pk):
        old.status, old.token_hash, old.response_note = Quotation.QStatus.SUPERSEDED, None, "Replaced by a newer quotation"
        old.save()
    raw = secrets.token_urlsafe(32)
    q.status, q.token_hash, q.sent_at = Quotation.QStatus.SENT, _hash(raw), timezone.now()
    q.save()
    if req.status == S.UNDER_REVIEW:
        _move(req, S.QUOTATION_SENT, request.user, f"Quotation v{q.version} sent", notify=False)
    _tell_customer(req, "catering_quotation", {"total": f"{q.currency} {q.total}", "valid_until": q.valid_until.isoformat(),
                                               "url": f"{req.restaurant.public_url}/quotation/{raw}"}, f"catering:{q.pk}:quotation")
    audit("catering.quotation_sent", actor=request.user, restaurant=req.restaurant, obj=q, request=request)
    return q


def _accept(req, q, via, note, actor):
    q.status, q.responded_at, q.accepted_via, q.response_note = Quotation.QStatus.ACCEPTED, timezone.now(), via, note[:300]
    q.token_hash = None
    q.save()
    _move(req, S.ACCEPTED, actor, f"Quotation v{q.version} accepted ({'by customer' if via == 'customer_link' else 'recorded by staff'})", notify=False)
    _tell_customer(req, "catering_status", {"status": label(S.ACCEPTED), "note": ""}, f"catering:{req.pk}:status:accepted")
    if req.restaurant.contact_email:
        queue_email("catering_staff_alert", req.restaurant.contact_email, {"reference": req.reference, "event": f"Quotation v{q.version} accepted",
                    "date": req.event_date.isoformat(), "guests": req.guests, "url": f"{req.restaurant.public_url}/manage/catering"},
                    restaurant=req.restaurant, dedupe_key=f"catering:{q.pk}:accepted-alert")
    audit("catering.quotation_accepted", actor=actor, restaurant=req.restaurant, obj=q, metadata={"via": via})


@transaction.atomic
def record_acceptance(request, request_id, quotation_id, note, qs):
    """Staff record that the customer accepted outside the portal (phone, in person). A note is mandatory."""
    req = lock(request_id, request.tenant, qs)
    q = Quotation.objects.select_for_update().filter(pk=quotation_id, request=req).first()
    if q is None:
        raise NotFound()
    if q.status != Quotation.QStatus.SENT or req.status != S.QUOTATION_SENT:
        raise serializers.ValidationError({"detail": "Only the quotation that was sent to the customer can be marked as accepted."})
    if not note.strip():
        raise serializers.ValidationError({"note": "Describe how and when the customer accepted."})
    _accept(req, q, "recorded_by_staff", note, request.user)
    return q


def quotation_by_token(token, tenant):
    """The link only works on its own restaurant's website (a bearer token plus the tenant host)."""
    q = (Quotation.unscoped.select_related("request", "restaurant").filter(token_hash=_hash(token or ""), status=Quotation.QStatus.SENT, restaurant=tenant).first()
         if token and tenant is not None else None)
    if q is None:
        raise NotFound("This link is not valid.")
    return q


@transaction.atomic
def respond_public(request, token, accept, note):
    q = quotation_by_token(token, request.tenant)
    q = Quotation.unscoped.select_for_update().select_related("request", "restaurant").get(pk=q.pk)
    req = CateringRequest.objects.select_for_update().select_related("restaurant", "branch").get(pk=q.request_id)
    if q.status != Quotation.QStatus.SENT or req.status != S.QUOTATION_SENT:
        raise NotFound("This link is no longer valid.")
    if q.valid_until < timezone.now().date():
        raise serializers.ValidationError({"detail": "This quotation has expired. Please contact the restaurant for a new one."})
    if accept:
        _accept(req, q, "customer_link", note, None)
    else:
        q.status, q.responded_at, q.response_note, q.token_hash = Quotation.QStatus.DECLINED, timezone.now(), note[:300], None
        q.save()
        _move(req, S.UNDER_REVIEW, None, f"Customer declined quotation v{q.version}" + (f": {note[:200]}" if note else ""), notify=False)
        audit("catering.quotation_declined", restaurant=req.restaurant, obj=q)
        if req.restaurant.contact_email:
            queue_email("catering_staff_alert", req.restaurant.contact_email, {"reference": req.reference, "event": f"Quotation v{q.version} declined",
                        "date": req.event_date.isoformat(), "guests": req.guests, "url": f"{req.restaurant.public_url}/manage/catering"},
                        restaurant=req.restaurant, dedupe_key=f"catering:{q.pk}:declined-alert")
    return q


# ---- payments --------------------------------------------------------------------------------------------------------
@transaction.atomic
def record_payment(request, request_id, data, qs):
    req = lock(request_id, request.tenant, qs)
    kind = data["kind"]
    allowed = (S.ACCEPTED, S.IN_PROGRESS, S.COMPLETED) + ((S.CANCELLED,) if kind == "refund" else ())
    if req.status not in allowed:
        raise serializers.ValidationError({"detail": "Payments can only be recorded for an accepted booking."})
    bal = balance(req)
    amount = m(data["amount"])
    if kind == "refund":
        if amount > bal["paid"]:
            raise serializers.ValidationError({"amount": f"At most {bal['paid']} can be refunded."})
    elif amount > bal["balance"]:
        raise serializers.ValidationError({"amount": f"The remaining balance is {bal['balance']}."})
    if data["received_on"] > timezone.now().date():
        raise serializers.ValidationError({"received_on": "The date cannot be in the future."})
    p = CateringPayment.objects.create(restaurant=req.restaurant, request=req, kind=kind, amount=amount, method=data["method"],
                                       reference=data["reference"], received_on=data["received_on"], note=data["note"], recorded_by=request.user)
    audit("catering.payment_recorded", actor=request.user, restaurant=req.restaurant, obj=p, metadata={"kind": kind, "amount": str(amount)}, request=request)
    after = balance(req)
    _tell_customer(req, "catering_payment", {"kind": kind, "amount": f"{req.currency} {amount}", "balance": f"{req.currency} {after['balance']}"}, f"catering:payment:{p.pk}")
    return p
