from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.permissions import IsManagerOrAbove, accessible_branch_ids, effective_role
from apps.catalog.models import Service
from apps.core.idempotency import run_idempotent
from apps.tenants.models import Branch

from . import services
from .models import CateringPayment, CateringRequest, EventType, Status
from .services import MANUAL_TARGETS, PAYMENT_METHODS, TRANSITIONS, balance, label

MONEY = dict(max_digits=12, decimal_places=2)


def _name(u):
    return (u.full_name or u.email) if u else None


# ======================= public ======================================================================
class PublicBase(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []


class PublicOptionsView(PublicBase):
    def get(self, request):
        t = request.tenant
        if t is None:
            from rest_framework.exceptions import NotFound
            raise NotFound()
        return Response({
            "event_types": [{"value": v, "label": l} for v, l in EventType.choices],
            "services": [{"id": s.pk, "name": s.name} for s in Service.unscoped.filter(restaurant=t, is_active=True)],
            "branches": [{"id": b.pk, "name": b.name} for b in Branch.unscoped.filter(restaurant=t, status="active")],
            "currency": t.get_settings().currency,
        })


class RequestInput(serializers.Serializer):
    customer_name = serializers.CharField(max_length=150)
    customer_email = serializers.EmailField()
    customer_phone = serializers.RegexField(r"^[0-9+()\-\s]{6,30}$", error_messages={"invalid": "Enter a valid phone number."})
    event_type = serializers.ChoiceField(choices=EventType.choices)
    event_date = serializers.DateField()
    event_location = serializers.CharField(max_length=250)
    guests = serializers.IntegerField(min_value=1, max_value=5000)
    service_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list, max_length=20)
    branch_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    food_preferences = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    budget = serializers.DecimalField(required=False, allow_null=True, default=None, min_value=Decimal("0"), **MONEY)
    requirements = serializers.CharField(max_length=3000, required=False, allow_blank=True, default="")
    accept_privacy = serializers.BooleanField()
    website = serializers.CharField(required=False, allow_blank=True, default="")  # honeypot

    def validate_event_date(self, v):
        today = timezone.now().date()
        if not (today + timedelta(days=1) <= v <= today + timedelta(days=730)):
            raise serializers.ValidationError("Choose a date between tomorrow and two years from now.")
        return v

    def validate_accept_privacy(self, v):
        if v is not True:
            raise serializers.ValidationError("You must agree to the Privacy Policy so we can contact you about your event.")
        return v

    def validate_website(self, v):
        if v:
            raise serializers.ValidationError("Invalid request.")
        return v


class PublicSubmitView(PublicBase):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "catering"

    def post(self, request):
        s = RequestInput(data=request.data)
        s.is_valid(raise_exception=True)
        req = services.submit_public(request, dict(s.validated_data))
        return Response({"reference": req.reference, "message": "Thank you. We have received your request and emailed you a confirmation."}, status=201)


def quote_public(q):
    r = q.request
    return {"reference": r.reference, "restaurant": q.restaurant.name, "currency": q.currency, "version": q.version,
            "event": {"type": r.get_event_type_display(), "date": r.event_date, "guests": r.guests, "location": r.event_location},
            "items": q.items, "subtotal": str(q.subtotal), "discount": str(q.discount), "tax_rate_percent": str(q.tax_rate_percent),
            "tax_total": str(q.tax_total), "total": str(q.total), "valid_until": q.valid_until, "terms": q.terms,
            "expired": q.valid_until < timezone.now().date()}


class PublicQuotationView(PublicBase):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "catering"

    def get(self, request, token):
        return Response(quote_public(services.quotation_by_token(token, request.tenant)))


class RespondInput(serializers.Serializer):
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class PublicQuotationRespondView(PublicBase):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "catering"
    accept = True

    def post(self, request, token):
        s = RespondInput(data=request.data)
        s.is_valid(raise_exception=True)
        services.respond_public(request, token, self.accept, s.validated_data["note"])
        return Response({"status": "accepted" if self.accept else "declined"})


class PublicQuotationDeclineView(PublicQuotationRespondView):
    accept = False


# ======================= staff ======================================================================
def scoped(request):
    base = CateringRequest.unscoped.filter(restaurant=request.tenant)
    if effective_role(request) in ("platform_admin", "restaurant_admin"):
        return base
    return base.filter(branch_id__in=accessible_branch_ids(request))  # managers: only requests allocated to their branches


def list_row(r):
    return {"id": r.pk, "reference": r.reference, "status": r.status, "status_label": label(r.status), "customer_name": r.customer_name,
            "event_type": r.event_type, "event_type_label": r.get_event_type_display(), "event_date": r.event_date, "guests": r.guests,
            "branch": {"id": r.branch_id, "name": r.branch.name} if r.branch_id else None, "assigned_to": _name(r.assigned_to),
            "assigned_to_id": r.assigned_to_id, "created_at": r.created_at}


def quote_json(q):
    return {"id": q.pk, "version": q.version, "status": q.status, "items": q.items, "subtotal": str(q.subtotal), "discount": str(q.discount),
            "tax_rate_percent": str(q.tax_rate_percent), "tax_total": str(q.tax_total), "total": str(q.total), "currency": q.currency,
            "valid_until": q.valid_until, "terms": q.terms, "sent_at": q.sent_at, "responded_at": q.responded_at, "accepted_via": q.accepted_via,
            "response_note": q.response_note, "created_by": _name(q.created_by)}


def detail_json(r):
    b = balance(r)
    return {**list_row(r), "customer_email": r.customer_email, "customer_phone": r.customer_phone, "event_location": r.event_location,
            "services": [s.name for s in r.services.all()], "food_preferences": r.food_preferences, "budget": str(r.budget) if r.budget is not None else None,
            "currency": r.currency, "requirements": r.requirements, "cancel_reason": r.cancel_reason,
            "allowed_statuses": [{"status": s, "label": label(s)} for s in sorted(TRANSITIONS[r.status]) if s in MANUAL_TARGETS],
            "history": [{"status": h.to_status, "label": label(h.to_status), "note": h.note, "actor": _name(h.actor), "created_at": h.created_at} for h in r.history.select_related("actor")],
            "notes": [{"id": n.pk, "kind": n.kind, "text": n.text, "author": _name(n.author), "created_at": n.created_at} for n in r.notes.select_related("author")],
            "quotations": [quote_json(q) for q in r.quotations.select_related("created_by")],
            "payments": [{"id": p.pk, "kind": p.kind, "amount": str(p.amount), "method": p.method, "reference": p.reference, "received_on": p.received_on,
                          "note": p.note, "recorded_by": _name(p.recorded_by)} for p in r.payments.select_related("recorded_by")],
            "balance": {k: str(v) for k, v in b.items()}}


class StatusInput(serializers.Serializer):
    status = serializers.ChoiceField(choices=Status.values)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class NoteInput(serializers.Serializer):
    text = serializers.CharField(min_length=1, max_length=3000)


class ContactInput(serializers.Serializer):
    subject = serializers.CharField(max_length=150)
    message = serializers.CharField(min_length=1, max_length=2000)


class ItemInput(serializers.Serializer):
    description = serializers.CharField(max_length=200)
    quantity = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=Decimal("0.01"), max_value=Decimal("10000"))
    unit_price = serializers.DecimalField(min_value=Decimal("0"), **MONEY)


class QuotationInput(serializers.Serializer):
    items = ItemInput(many=True, allow_empty=False, max_length=40)
    discount = serializers.DecimalField(min_value=Decimal("0"), default=Decimal("0"), **MONEY)
    valid_until = serializers.DateField()
    terms = serializers.CharField(max_length=3000, required=False, allow_blank=True, default="")


class PaymentInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=CateringPayment.Kind.values)
    amount = serializers.DecimalField(min_value=Decimal("0.01"), **MONEY)
    method = serializers.ChoiceField(choices=PAYMENT_METHODS)
    reference = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    received_on = serializers.DateField()
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class CateringViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsManagerOrAbove]

    def get_queryset(self):
        qs = scoped(self.request).select_related("branch", "assigned_to")
        p = self.request.query_params
        if p.get("status") in Status.values:
            qs = qs.filter(status=p["status"])
        if p.get("assigned") == "me":
            qs = qs.filter(assigned_to=self.request.user)
        if p.get("unallocated") == "1":
            qs = qs.filter(branch__isnull=True)
        if q := p.get("q", "").strip():
            qs = qs.filter(Q(reference__icontains=q) | Q(customer_name__icontains=q) | Q(customer_email__icontains=q))
        if (d := parse_date(p.get("event_from", ""))):
            qs = qs.filter(event_date__gte=d)
        if (d := parse_date(p.get("event_to", ""))):
            qs = qs.filter(event_date__lte=d)
        return qs

    def list(self, request, *args, **kwargs):
        counts = dict(scoped(request).values_list("status").annotate(n=Count("id")))
        page = self.paginate_queryset(self.get_queryset())
        resp = self.get_paginated_response([list_row(r) for r in page])
        resp.data["counts"] = {s: counts.get(s, 0) for s in Status.values}
        return resp

    def retrieve(self, request, *args, **kwargs):
        return Response(detail_json(self.get_object()))

    def _fresh(self, request, pk):
        return Response(detail_json(self.get_queryset().get(pk=pk)))

    @action(detail=True, methods=["post"])
    def status(self, request, pk=None):
        s = StatusInput(data=request.data)
        s.is_valid(raise_exception=True)
        services.change_status(request, pk, s.validated_data["status"], s.validated_data["note"], scoped(request))
        return self._fresh(request, pk)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        uid = request.data.get("user_id")
        if uid is not None and not isinstance(uid, int):
            raise serializers.ValidationError({"user_id": "Invalid staff member."})
        services.assign(request, pk, uid, scoped(request))
        return self._fresh(request, pk)

    @action(detail=True, methods=["post"], url_path="set-branch")
    def set_branch(self, request, pk=None):
        self.get_object()  # unseen requests are 404 before any role message
        if effective_role(request) not in ("platform_admin", "restaurant_admin"):
            raise serializers.ValidationError({"detail": "Only the restaurant administrator can allocate a branch."})
        services.set_branch(request, pk, request.data.get("branch_id"), scoped(request))
        return self._fresh(request, pk)

    @action(detail=True, methods=["post"])
    def notes(self, request, pk=None):
        s = NoteInput(data=request.data)
        s.is_valid(raise_exception=True)
        services.add_note(request, pk, s.validated_data["text"], scoped(request))
        return self._fresh(request, pk)

    @action(detail=True, methods=["post"])
    def contact(self, request, pk=None):
        s = ContactInput(data=request.data)
        s.is_valid(raise_exception=True)
        services.contact_customer(request, pk, s.validated_data["subject"], s.validated_data["message"], scoped(request))
        return self._fresh(request, pk)

    @action(detail=True, methods=["post"])
    def quotations(self, request, pk=None):
        s = QuotationInput(data=request.data)
        s.is_valid(raise_exception=True)
        services.create_quotation(request, pk, dict(s.validated_data), scoped(request))
        return self._fresh(request, pk)

    @action(detail=True, methods=["post"], url_path=r"quotations/(?P<qid>\d+)/send")
    def send_quotation(self, request, pk=None, qid=None):
        services.send_quotation(request, pk, int(qid), scoped(request))
        return self._fresh(request, pk)

    @action(detail=True, methods=["post"], url_path=r"quotations/(?P<qid>\d+)/accept")
    def accept_quotation(self, request, pk=None, qid=None):
        services.record_acceptance(request, pk, int(qid), str(request.data.get("note", "")), scoped(request))
        return self._fresh(request, pk)

    @action(detail=True, methods=["post"])
    def payments(self, request, pk=None):
        s = PaymentInput(data=request.data)
        s.is_valid(raise_exception=True)

        def handler():
            p = services.record_payment(request, pk, dict(s.validated_data), scoped(request))
            return 201, {"id": p.pk, "balance": {k: str(v) for k, v in balance(p.request).items()}}

        status, body = run_idempotent(request, f"catering.payment:{pk}", request.headers.get("Idempotency-Key", ""), request.data, handler)
        return Response(body, status=status)
