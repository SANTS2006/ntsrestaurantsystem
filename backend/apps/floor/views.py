from datetime import date

from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.permissions import IsCashierOrAbove, IsManagerOrAbove, accessible_branch_ids
from apps.core.models import audit
from apps.core.pagination import StandardPagination
from apps.qrmenu.models import DiningTable
from apps.tenants.models import Branch

from . import services
from .models import FloorZone, Reservation

S = Reservation.Status


def _tenant(request):
    if request.tenant is None:
        raise NotFound()
    return request.tenant


def res_json(r, with_contact=True):
    local = r.starts_at.astimezone(services.tz_of(r.restaurant))
    d = {"id": r.pk, "reference": r.reference, "status": r.status, "branch": r.branch.name, "branch_id": r.branch_id, "starts_at": r.starts_at, "local_date": local.date().isoformat(), "local_time": local.strftime("%H:%M"),
         "duration_minutes": r.duration_minutes, "party_size": r.party_size, "table": r.table.label if r.table_id else None, "table_id": r.table_id, "notes": r.notes, "source": r.source, "seated_at": r.seated_at,
         "cancel_reason": r.cancel_reason}
    if with_contact:
        d.update(customer_name=r.customer_name, customer_phone=r.customer_phone, customer_email=r.customer_email)
    return d


# ======================================================================== public
class PublicBase(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []


class OptionsView(PublicBase):
    def get(self, request):
        t = _tenant(request)
        st = t.get_settings()
        return Response({"enabled": st.reservations_enabled, "max_party": st.reservation_max_party, "duration_minutes": st.reservation_duration_minutes, "auto_confirm": st.reservation_auto_confirm,
                        "branches": [{"id": b.pk, "name": b.name, "operating_hours": b.operating_hours} for b in Branch.unscoped.filter(restaurant=t, status="active")]})


class AvailabilityView(PublicBase):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "reservations"

    def get(self, request):
        t = _tenant(request)
        p = request.query_params
        try:
            day, party, bid = date.fromisoformat(p.get("date", "")), int(p.get("party", "0")), int(p.get("branch", "0"))
        except ValueError:
            raise serializers.ValidationError({"detail": "Choose a branch, a date and a party size."})
        branch = Branch.unscoped.filter(pk=bid, restaurant=t, status="active").first()
        if branch is None:
            raise NotFound()
        if party < 1 or party > t.get_settings().reservation_max_party:
            raise serializers.ValidationError({"party": "Choose a valid party size."})
        today = timezone.now().astimezone(services.tz_of(t)).date()
        if day < today or (day - today).days > services.HORIZON_DAYS:
            return Response({"date": day.isoformat(), "slots": []})
        return Response({"date": day.isoformat(), "slots": services.slots(t, branch, day, party)})


class BookInput(serializers.Serializer):
    branch_id = serializers.IntegerField()
    date = serializers.DateField()
    time = serializers.RegexField(r"^\d{2}:\d{2}$")
    party_size = serializers.IntegerField(min_value=1, max_value=100)
    customer_name = serializers.CharField(max_length=150)
    customer_phone = serializers.RegexField(r"^[0-9+()\-\s]{6,30}$", error_messages={"invalid": "Enter a valid phone number."})
    customer_email = serializers.EmailField(required=False, allow_blank=True)
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True)
    accept_privacy = serializers.BooleanField()
    website = serializers.CharField(required=False, allow_blank=True, default="")  # honeypot

    def validate(self, a):
        if a["website"]:
            raise serializers.ValidationError("Invalid request.")
        if not a["accept_privacy"]:
            raise serializers.ValidationError({"accept_privacy": "Please accept the privacy policy so we can hold your booking."})
        return a


class BookView(PublicBase):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "reservations"

    def post(self, request):
        t = _tenant(request)
        s = BookInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        branch = Branch.unscoped.filter(pk=d["branch_id"], restaurant=t, status="active").first()
        if branch is None:
            raise serializers.ValidationError({"branch_id": "Choose a valid branch."})
        try:
            hh, mm = map(int, d["time"].split(":"))
            from datetime import datetime, time
            from zoneinfo import ZoneInfo

            start = datetime.combine(d["date"], time(hh, mm), tzinfo=services.tz_of(t)).astimezone(ZoneInfo("UTC"))
        except ValueError:
            raise serializers.ValidationError({"time": "Enter a valid time."})
        r = services.create_reservation(t, branch, {**d, "starts_at": start}, source="public")
        body = res_json(Reservation.unscoped.select_related("branch", "table", "restaurant").get(pk=r.pk), with_contact=False)
        body["manage_token"] = r.raw_token  # shown once on the confirmation screen and emailed; only its hash is stored
        return Response(body, status=201)


class GuestReservationView(PublicBase):
    def get(self, request, token):
        t = _tenant(request)
        r = Reservation.unscoped.select_related("branch", "table", "restaurant").filter(restaurant=t, token_hash=services.hash_token(token)).first()
        if r is None:
            raise NotFound()
        return Response(res_json(r, with_contact=False))

    def post(self, request, token):
        r = services.guest_cancel(_tenant(request), token)
        return Response(res_json(Reservation.unscoped.select_related("branch", "table", "restaurant").get(pk=r.pk), with_contact=False))


# ======================================================================== staff
class StaffBase(APIView):
    permission_classes = [IsCashierOrAbove]


class ReservationsView(StaffBase):
    def get(self, request):
        qs = Reservation.unscoped.filter(restaurant=request.tenant, branch_id__in=accessible_branch_ids(request)).select_related("branch", "table", "restaurant")
        p = request.query_params
        tz = services.tz_of(request.tenant)
        if p.get("date"):
            try:
                from datetime import datetime, time, timedelta

                day = date.fromisoformat(p["date"])
            except ValueError:
                raise serializers.ValidationError({"date": "Use the format YYYY-MM-DD."})
            lo = datetime.combine(day, time(0, 0), tzinfo=tz)
            qs = qs.filter(starts_at__gte=lo, starts_at__lt=lo + timedelta(days=1))
        if p.get("status") in S.values:
            qs = qs.filter(status=p["status"])
        if p.get("branch", "").isdigit():
            qs = qs.filter(branch_id=int(p["branch"]))
        if q := p.get("q", "").strip()[:100]:
            qs = qs.filter(customer_name__icontains=q) | qs.filter(reference__icontains=q) | qs.filter(customer_phone__icontains=q)
        pager = StandardPagination()
        page = pager.paginate_queryset(qs.order_by("starts_at", "id"), request)
        return pager.get_paginated_response([res_json(r) for r in page])

    def post(self, request):
        class In(BookInput):
            accept_privacy = serializers.BooleanField(required=False)
            time = serializers.RegexField(r"^\d{2}:\d{2}$")
            table_id = serializers.IntegerField(required=False, allow_null=True)

            def validate(self, a):
                return a

        s = In(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        branch = services.branch_of(request, d["branch_id"])
        from datetime import datetime, time
        from zoneinfo import ZoneInfo

        hh, mm = map(int, d["time"].split(":"))
        start = datetime.combine(d["date"], time(hh, mm), tzinfo=services.tz_of(request.tenant)).astimezone(ZoneInfo("UTC"))
        r = services.create_reservation(request.tenant, branch, {**d, "starts_at": start}, source="staff", user=request.user, table_id=d.get("table_id"))
        return Response(res_json(Reservation.unscoped.select_related("branch", "table", "restaurant").get(pk=r.pk)), status=201)


class ReservationView(StaffBase):
    def get(self, request, pk):
        return Response(res_json(services._staff_get(request, pk)))

    def patch(self, request, pk):
        class In(serializers.Serializer):
            date = serializers.DateField(required=False)
            time = serializers.RegexField(r"^\d{2}:\d{2}$", required=False)
            party_size = serializers.IntegerField(min_value=1, max_value=100, required=False)
            table_id = serializers.IntegerField(required=False)
            customer_name = serializers.CharField(max_length=150, required=False)
            customer_phone = serializers.RegexField(r"^[0-9+()\-\s]{6,30}$", required=False)
            customer_email = serializers.EmailField(required=False, allow_blank=True)
            notes = serializers.CharField(max_length=300, required=False, allow_blank=True)

        s = In(data=request.data)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        r0 = services._staff_get(request, pk)
        if "date" in d or "time" in d:
            from datetime import datetime, time
            from zoneinfo import ZoneInfo

            tz = services.tz_of(request.tenant)
            local = r0.starts_at.astimezone(tz)
            day = d.pop("date", local.date())
            hh, mm = map(int, d.pop("time", local.strftime("%H:%M")).split(":"))
            d["starts_at"] = datetime.combine(day, time(hh, mm), tzinfo=tz).astimezone(ZoneInfo("UTC"))
        r = services.update_reservation(request, pk, d)
        return Response(res_json(Reservation.unscoped.select_related("branch", "table", "restaurant").get(pk=r.pk)))


class ReservationActionView(StaffBase):
    ACTIONS = {"confirm": S.CONFIRMED, "seat": S.SEATED, "complete": S.COMPLETED, "cancel": S.CANCELLED, "no-show": S.NO_SHOW}

    def post(self, request, pk, act):
        if act not in self.ACTIONS:
            raise NotFound()
        r = services.move(request, pk, self.ACTIONS[act], str(request.data.get("reason", "")))
        return Response(res_json(Reservation.unscoped.select_related("branch", "table", "restaurant").get(pk=r.pk)))


class StatusView(StaffBase):
    def get(self, request):
        bid = request.query_params.get("branch", "")
        allowed = sorted(accessible_branch_ids(request))
        if not bid and len(allowed) == 1:
            bid = str(allowed[0])
        if not bid.isdigit():
            raise serializers.ValidationError({"branch": "Choose a branch."})
        branch = services.branch_of(request, int(bid))
        zones = services.floor_status(request.tenant, branch)
        counts = {"free": 0, "reserved": 0, "occupied": 0}
        for z in zones:
            for t in z["tables"]:
                counts[t["state"]] += 1
        return Response({"branch": branch.name, "branch_id": branch.pk, "counts": counts, "zones": zones})


# ======================================================================== zones and layout (managers)
class ZonesView(APIView):
    def get_permissions(self):
        return [IsCashierOrAbove()] if self.request.method == "GET" else [IsManagerOrAbove()]

    def get(self, request):
        qs = FloorZone.unscoped.filter(restaurant=request.tenant, branch_id__in=accessible_branch_ids(request)).select_related("branch")
        return Response([{"id": z.pk, "name": z.name, "branch_id": z.branch_id, "branch": z.branch.name, "sort_order": z.sort_order, "is_active": z.is_active} for z in qs])

    def post(self, request):
        name = str(request.data.get("name", "")).strip()
        branch = services.branch_of(request, int(request.data.get("branch_id") or 0))
        if not name or len(name) > 60:
            raise serializers.ValidationError({"name": "Enter a zone name of up to 60 characters."})
        if FloorZone.unscoped.filter(branch=branch, name__iexact=name).exists():
            raise serializers.ValidationError({"name": "This branch already has a zone with that name."})
        z = FloorZone.objects.create(restaurant=request.tenant, branch=branch, name=name, sort_order=int(request.data.get("sort_order") or 0))
        audit("floor.zone_created", actor=request.user, restaurant=request.tenant, obj=z, request=request)
        return Response({"id": z.pk, "name": z.name, "branch_id": branch.pk, "branch": branch.name, "sort_order": z.sort_order, "is_active": True}, status=201)


class ZoneView(APIView):
    permission_classes = [IsManagerOrAbove]

    def patch(self, request, pk):
        z = FloorZone.unscoped.filter(pk=pk, restaurant=request.tenant, branch_id__in=accessible_branch_ids(request)).first()
        if z is None:
            raise NotFound()
        if "name" in request.data:
            name = str(request.data["name"]).strip()
            if not name or FloorZone.unscoped.filter(branch=z.branch, name__iexact=name).exclude(pk=z.pk).exists():
                raise serializers.ValidationError({"name": "Choose a unique zone name."})
            z.name = name[:60]
        if "sort_order" in request.data:
            z.sort_order = max(0, min(int(request.data["sort_order"]), 1000))
        if "is_active" in request.data:
            z.is_active = bool(request.data["is_active"])
        z.save()
        return Response({"id": z.pk, "name": z.name, "sort_order": z.sort_order, "is_active": z.is_active})


class TableLayoutView(APIView):
    permission_classes = [IsManagerOrAbove]

    def patch(self, request, pk):
        t = DiningTable.unscoped.filter(pk=pk, restaurant=request.tenant, branch_id__in=accessible_branch_ids(request)).first()
        if t is None:
            raise NotFound()

        class In(serializers.Serializer):
            zone_id = serializers.IntegerField(required=False, allow_null=True)
            shape = serializers.ChoiceField(choices=["square", "round", "rect"], required=False)
            pos_x = serializers.IntegerField(min_value=0, max_value=100, required=False)
            pos_y = serializers.IntegerField(min_value=0, max_value=100, required=False)
            seats = serializers.IntegerField(min_value=1, max_value=50, required=False)

        s = In(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        if "zone_id" in d:
            if d["zone_id"] is None:
                t.zone = None
            else:
                z = FloorZone.unscoped.filter(pk=d["zone_id"], restaurant=request.tenant, branch_id=t.branch_id).first()
                if z is None:
                    raise serializers.ValidationError({"zone_id": "Choose a zone of the same branch."})
                t.zone = z
        for f in ("shape", "pos_x", "pos_y", "seats"):
            if f in d:
                setattr(t, f, d[f])
        t.save()
        audit("floor.table_layout_changed", actor=request.user, restaurant=request.tenant, obj=t, metadata={"fields": sorted(d)}, request=request)
        return Response({"id": t.pk, "label": t.label, "zone_id": t.zone_id, "shape": t.shape, "pos_x": t.pos_x, "pos_y": t.pos_y, "seats": t.seats})
