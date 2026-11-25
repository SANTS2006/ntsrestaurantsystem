"""Reservations and the floor status board.

Double-booking is prevented by row-locking every active table of the branch (in id order) before checking overlaps, so two
guests racing for the last table are serialised. Times are stored in UTC and interpreted in the restaurant's time zone.
"""
import hashlib
import secrets
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound

from apps.core.models import audit, next_document_number
from apps.notifications.services import queue_email
from apps.orders.models import Order
from apps.qrmenu.models import DiningTable
from apps.tenants.models import Branch

from .models import Reservation

S = Reservation.Status
HOLDING = (S.REQUESTED, S.CONFIRMED, S.SEATED)
LEAD = timedelta(minutes=30)
HORIZON_DAYS = 60
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DEFAULT_SEATS = 4  # tables without a seat count are treated as four-tops


def _fail(msg, field="detail"):
    raise serializers.ValidationError({field: msg})


def tz_of(tenant):
    try:
        return ZoneInfo(tenant.get_settings().timezone)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def hash_token(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def seats(t):
    return t.seats or DEFAULT_SEATS


def opening(branch, day: date):
    """(open, close) as naive times for that weekday, or None if closed. No hours configured at all = open 09:00-22:00."""
    hours = branch.operating_hours or {}
    if not hours:
        return datetime.min.replace(hour=9).time(), datetime.min.replace(hour=22).time()
    raw = hours.get(DAYS[day.weekday()])
    if not raw or "-" not in str(raw):
        return None
    try:
        a, b = str(raw).split("-", 1)
        return datetime.strptime(a.strip(), "%H:%M").time(), datetime.strptime(b.strip(), "%H:%M").time()
    except ValueError:
        return None


def _busy(table_ids, start, end, exclude=None):
    qs = Reservation.unscoped.filter(table_id__in=table_ids, status__in=HOLDING, starts_at__lt=end)
    if exclude:
        qs = qs.exclude(pk=exclude)
    busy = set()
    for r in qs.only("table_id", "starts_at", "duration_minutes"):
        if r.starts_at + timedelta(minutes=r.duration_minutes) > start:
            busy.add(r.table_id)
    return busy


def free_tables(branch, start, minutes, party, *, exclude=None, lock=False):
    qs = DiningTable.unscoped.filter(branch=branch, is_active=True).order_by("pk")
    tables = list(qs.select_for_update() if lock else qs)
    end = start + timedelta(minutes=minutes)
    busy = _busy([t.pk for t in tables], start, end, exclude)
    return sorted((t for t in tables if t.pk not in busy and seats(t) >= party), key=lambda t: (seats(t), t.pk))


def slots(tenant, branch, day: date, party: int):
    st = tenant.get_settings()
    tz = tz_of(tenant)
    window = opening(branch, day)
    if window is None or not st.reservations_enabled:
        return []
    dur = st.reservation_duration_minutes
    now = timezone.now()
    cur = datetime.combine(day, window[0], tzinfo=tz)
    last = datetime.combine(day, window[1], tzinfo=tz) - timedelta(minutes=dur)
    out = []
    while cur <= last:
        start = cur.astimezone(ZoneInfo("UTC"))
        if start >= now + LEAD and free_tables(branch, start, dur, party):
            out.append(cur.strftime("%H:%M"))
        cur += timedelta(minutes=30)
    return out


def _validate_when(tenant, branch, start, party, *, staff=False):
    st = tenant.get_settings()
    if not st.reservations_enabled and not staff:
        _fail("Reservations are not available.")
    if party < 1 or party > st.reservation_max_party:
        _fail(f"We take bookings for 1 to {st.reservation_max_party} guests online. Please call for larger groups.", "party_size")
    now = timezone.now()
    if not staff and start < now + LEAD:
        _fail("Please book at least 30 minutes ahead.", "starts_at")
    if start > now + timedelta(days=HORIZON_DAYS):
        _fail(f"Bookings open up to {HORIZON_DAYS} days ahead.", "starts_at")
    local = start.astimezone(tz_of(tenant))
    window = opening(branch, local.date())
    end_local = local + timedelta(minutes=st.reservation_duration_minutes)
    if window is None or not (window[0] <= local.time() and end_local.time() <= window[1] and end_local.date() == local.date()):
        _fail("The restaurant is not open for a full sitting at that time.", "starts_at")


def local_when(r, tenant):
    return r.starts_at.astimezone(tz_of(tenant)).strftime("%a %d %b, %H:%M")


@transaction.atomic
def create_reservation(tenant, branch, d, *, source="public", user=None, table_id=None):
    st = tenant.get_settings()
    dur = st.reservation_duration_minutes
    start, party = d["starts_at"], d["party_size"]
    _validate_when(tenant, branch, start, party, staff=source == "staff")
    free = free_tables(branch, start, dur, party, lock=True)  # row locks serialise concurrent bookings of this branch
    if table_id:
        table = next((t for t in free if t.pk == table_id), None)
        if table is None:
            _fail("That table is not free for this time or is too small.", "table_id")
    elif free:
        table = free[0]
    else:
        _fail("No table is free at that time. Please choose another time.", "starts_at")
    raw = secrets.token_urlsafe(24)
    status = S.CONFIRMED if (st.reservation_auto_confirm or source == "staff") else S.REQUESTED
    r = Reservation.objects.create(
        restaurant=tenant, branch=branch, reference=next_document_number(tenant, "reservation", "RES"), customer_name=d["customer_name"].strip(), customer_phone=d["customer_phone"],
        customer_email=d.get("customer_email", ""), party_size=party, starts_at=start, duration_minutes=dur, table=table, status=status, notes=d.get("notes", ""), source=source,
        token_hash=hash_token(raw), created_by=user, consent_at=timezone.now() if source == "public" else None)
    audit("reservation.created", actor=user, restaurant=tenant, obj=r, metadata={"reference": r.reference, "party": party, "source": source}, request=None)
    if r.customer_email:
        local = start.astimezone(tz_of(tenant))
        queue_email("reservation_confirmed", r.customer_email, {"name": r.customer_name, "party": f"{party} guest{'s' if party != 1 else ''}", "when": local.strftime("%A %d %B, %H:%M"),
                                                                   "reference": r.reference, "url": f"{tenant.public_url}/reservation/{raw}"}, restaurant=tenant, dedupe_key=f"reservation:{r.pk}:created")
    r.raw_token = raw  # handed to the caller once; never stored
    from apps.notifications import inapp

    inapp.notify_staff(tenant, branch.pk, inapp.FRONT_OF_HOUSE, "reservation", f"New reservation {r.reference}", f"{r.customer_name} · {party} guest{'s' if party != 1 else ''} · {local_when(r, tenant)}", "/manage/floor")
    return r


@transaction.atomic
def update_reservation(request, pk, d):
    r = _staff_get(request, pk, lock=True)
    if r.status not in (S.REQUESTED, S.CONFIRMED):
        _fail("Only an upcoming reservation can be changed.")
    tenant = request.tenant
    start, party = d.get("starts_at", r.starts_at), d.get("party_size", r.party_size)
    _validate_when(tenant, r.branch, start, party, staff=True)
    free = free_tables(r.branch, start, r.duration_minutes, party, exclude=r.pk, lock=True)
    want = d.get("table_id", r.table_id)
    table = next((t for t in free if t.pk == want), None) or (free[0] if free and "table_id" not in d else None)
    if table is None:
        _fail("No suitable table is free for that change.", "table_id")
    for f in ("customer_name", "customer_phone", "customer_email", "notes"):
        if f in d:
            setattr(r, f, d[f])
    r.starts_at, r.party_size, r.table = start, party, table
    r.save()
    audit("reservation.updated", actor=request.user, restaurant=tenant, obj=r, metadata={"fields": sorted(d)}, request=request)
    return r


TRANSITIONS = {S.REQUESTED: {S.CONFIRMED, S.CANCELLED}, S.CONFIRMED: {S.SEATED, S.CANCELLED, S.NO_SHOW}, S.SEATED: {S.COMPLETED}}


@transaction.atomic
def move(request, pk, to, reason=""):
    r = _staff_get(request, pk, lock=True)
    if to not in TRANSITIONS.get(r.status, set()):
        _fail(f"A {r.status} reservation cannot be marked {to}.")
    if to == S.CANCELLED and len(reason.strip()) < 3:
        _fail("Give a reason.", "reason")
    if to == S.NO_SHOW and timezone.now() < r.starts_at:
        _fail("A guest cannot be a no-show before the booking time.")
    if to == S.SEATED:
        r.seated_at = timezone.now()
    if to == S.CANCELLED:
        r.cancel_reason = reason.strip()[:200]
    r.status = to
    r.save()
    audit(f"reservation.{to}", actor=request.user, restaurant=request.tenant, obj=r, metadata={"reference": r.reference}, request=request)
    if to == S.CANCELLED and r.customer_email:
        queue_email("reservation_cancelled", r.customer_email, {"name": r.customer_name, "reference": r.reference, "when": r.starts_at.astimezone(tz_of(request.tenant)).strftime("%A %d %B, %H:%M")},
                    restaurant=request.tenant, dedupe_key=f"reservation:{r.pk}:cancelled")
    return r


def _staff_get(request, pk, lock=False):
    from apps.accounts.permissions import accessible_branch_ids

    qs = Reservation.unscoped.filter(pk=pk, restaurant=request.tenant, branch_id__in=accessible_branch_ids(request))
    r = (qs.select_for_update() if lock else qs).select_related("branch", "table").first()
    if r is None:
        raise NotFound()
    return r


@transaction.atomic
def guest_cancel(tenant, raw_token):
    r = Reservation.unscoped.select_for_update().filter(restaurant=tenant, token_hash=hash_token(raw_token)).first() if raw_token else None
    if r is None:
        raise NotFound()
    if r.status not in (S.REQUESTED, S.CONFIRMED) or r.starts_at <= timezone.now():
        _fail("This reservation can no longer be cancelled online. Please call the restaurant.")
    r.status, r.cancel_reason = S.CANCELLED, "Cancelled by the guest"
    r.save()
    audit("reservation.cancelled", restaurant=tenant, obj=r, metadata={"reference": r.reference, "by": "guest"})
    return r


# ---- floor status board ------------------------------------------------------------------------------------------
def floor_status(tenant, branch):
    now = timezone.now()
    tables = list(DiningTable.unscoped.filter(branch=branch, is_active=True).select_related("zone").order_by("zone__sort_order", "label"))
    ids = [t.pk for t in tables]
    res = list(Reservation.unscoped.filter(table_id__in=ids, status__in=HOLDING, starts_at__lt=now + timedelta(hours=3)).order_by("starts_at"))
    open_orders = {o.table_id: o for o in Order.unscoped.filter(table_id__in=ids).exclude(status__in=["completed", "cancelled", "refunded"]).order_by("created_at")}
    by_zone: dict = {}
    for t in tables:
        seated = next((r for r in res if r.table_id == t.pk and r.status == S.SEATED), None)
        upcoming = next((r for r in res if r.table_id == t.pk and r.status in (S.REQUESTED, S.CONFIRMED) and r.starts_at + timedelta(minutes=r.duration_minutes) > now), None)
        order = open_orders.get(t.pk)
        state = "occupied" if (seated or order) else "reserved" if upcoming and upcoming.starts_at <= now + timedelta(minutes=60) else "free"
        row = {"id": t.pk, "label": t.label, "seats": t.seats, "shape": t.shape, "x": t.pos_x, "y": t.pos_y, "state": state,
               "occupied_by": ({"reference": seated.reference, "party": seated.party_size, "name": seated.customer_name} if seated else {"order": order.number} if order else None),
               "next_reservation": ({"id": upcoming.pk, "reference": upcoming.reference, "name": upcoming.customer_name, "party": upcoming.party_size, "at": upcoming.starts_at, "status": upcoming.status} if upcoming else None)}
        key = (t.zone.sort_order, t.zone.pk, t.zone.name) if t.zone_id else (9999, 0, "Unassigned")
        by_zone.setdefault(key, []).append(row)
    return [{"zone_id": k[1] or None, "zone": k[2], "tables": v} for k, v in sorted(by_zone.items())]


def branch_of(request, branch_id):
    from apps.accounts.permissions import accessible_branch_ids

    if branch_id not in accessible_branch_ids(request):
        raise NotFound()
    return Branch.unscoped.get(pk=branch_id, restaurant=request.tenant)
