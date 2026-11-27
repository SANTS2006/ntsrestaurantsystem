"""Contact forms, the team's message inbox, and the platform website's editable content."""
import hashlib
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.authentication import VersionedJWTAuthentication
from apps.accounts.models import Role
from apps.accounts.permissions import (IsManagerOrAbove, IsPlatformAdminOnPlatformHost, accessible_branch_ids,
                                       effective_role)
from apps.core.models import audit
from apps.core.pagination import StandardPagination
from apps.core.uploads import image_field
from apps.notifications.services import queue_email
from apps.tenants.models import PlatformSettings

from . import content, notify
from .models import HERO_SLOTS, ContactActivity, ContactMessage, PlatformContent, PlatformImage
from .serializers import ContactInput, message_detail, message_row

HERO_MAX_BYTES = 4 * 1024 * 1024


class OptionalJWT(VersionedJWTAuthentication):
    """Link the message to the sender's account when they happen to be signed in; an expired session never blocks the form."""

    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except Exception:  # noqa: BLE001
            return None


def _ip(request):
    from apps.accounts.services import client_ip

    try:
        return serializers.IPAddressField().run_validation(client_ip(request) or "")
    except serializers.ValidationError:
        return None


class ContactSubmitView(APIView):
    """Public contact form of the platform website, or of a restaurant website when the address names a restaurant."""

    permission_classes = [AllowAny]
    authentication_classes = [OptionalJWT]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "contact"

    def post(self, request):
        if request.tenant is None and not getattr(request, "is_platform", False):
            raise NotFound()
        thanks = {"received": True}
        if str(request.data.get("company_website", "")).strip():  # honeypot: people never see this field, form-filling bots do
            return Response(thanks, status=201)
        s = ContactInput(data=request.data, context={"request": request})
        s.is_valid(raise_exception=True)
        v = s.validated_data
        recent = ContactMessage.objects.filter(restaurant=request.tenant, email__iexact=v["email"], subject=v["subject"], message=v["message"],
                                               created_at__gte=timezone.now() - timedelta(minutes=10)).first()
        if recent:  # a double click or a retry: the first copy is already with the team
            return Response({**thanks, "reference": recent.reference}, status=201)
        user = request.user if request.user and request.user.is_authenticated else None
        with transaction.atomic():
            m = ContactMessage.objects.create(
                restaurant=request.tenant, branch=v["branch"], user=user, name=v["name"], email=v["email"].lower(), phone=v["phone"],
                business_name=v["business_name"], city=v["city"], preferred_contact=v["preferred_contact"], topic=v["topic"],
                subject=v["subject"], message=v["message"], page=v["page"], consented_at=timezone.now(),
                ip_address=_ip(request), user_agent=request.META.get("HTTP_USER_AGENT", "")[:300])
        notify.new_message(m)
        return Response({**thanks, "reference": m.reference}, status=201)


class CanHandleMessages(BasePermission):
    """The platform's messages: platform administrators on the platform address. A restaurant's: its managers and administrators."""

    def has_permission(self, request, view):
        if getattr(request, "tenant", None) is None:
            return IsPlatformAdminOnPlatformHost().has_permission(request, view)
        return IsManagerOrAbove().has_permission(request, view)


def visible_messages(request):
    qs = ContactMessage.objects.filter(restaurant=request.tenant).select_related("branch")
    if request.tenant is not None and effective_role(request) not in (Role.RESTAURANT_ADMIN, Role.PLATFORM_ADMIN):
        qs = qs.filter(Q(branch__isnull=True) | Q(branch_id__in=accessible_branch_ids(request)))
    return qs


class MessageList(ListAPIView):
    permission_classes = [CanHandleMessages]
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = visible_messages(self.request)
        status = self.request.query_params.get("status", "")
        if status in ContactMessage.Status.values:
            qs = qs.filter(status=status)
        elif status != "all":
            qs = qs.exclude(status=ContactMessage.Status.SPAM)
        if q := self.request.query_params.get("q", "").strip()[:100]:
            qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q) | Q(subject__icontains=q)
                           | Q(message__icontains=q) | Q(business_name__icontains=q))
        return qs

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        response = self.get_paginated_response([message_row(m) for m in page])
        counts = dict(visible_messages(request).values_list("status").annotate(n=Count("id")).order_by())
        response.data["counts"] = {k: counts.get(k, 0) for k in ContactMessage.Status.values}
        return response


class ActionInput(serializers.Serializer):
    action = serializers.ChoiceField(choices=["reply", "note", "status"])
    text = serializers.CharField(max_length=4000, required=False, allow_blank=True, default="")
    status = serializers.ChoiceField(choices=ContactMessage.Status.values, required=False)

    def validate(self, data):
        if data["action"] in ("reply", "note") and len(data["text"].strip()) < 2:
            raise serializers.ValidationError({"text": "Write your message first."})
        if data["action"] == "status" and not data.get("status"):
            raise serializers.ValidationError({"status": "Choose a status."})
        return data


class MessageDetail(APIView):
    permission_classes = [CanHandleMessages]

    def _get(self, request, pk, lock=False):
        qs = visible_messages(request)
        if lock:
            qs = qs.select_for_update(of=("self",))
        m = qs.filter(pk=pk).first()
        if m is None:
            raise NotFound()
        return m

    def get(self, request, pk):
        m = self._get(request, pk)
        audit("contact.viewed", actor=request.user, restaurant=request.tenant, obj=m, request=request)
        return Response(message_detail(m))

    def post(self, request, pk):
        s = ActionInput(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        text = v["text"].strip()
        with transaction.atomic():
            m = self._get(request, pk, lock=True)
            before = m.status
            if v["action"] == "reply":
                if m.status == ContactMessage.Status.SPAM:
                    raise ValidationError({"detail": "This message is marked as spam. Change its status before replying."})
                support = None if m.restaurant_id else (PlatformSettings.load().support_email or None)
                sent = queue_email("contact_reply", m.email,
                                   {"name": m.name, "subject": m.subject, "reply": text, "original": m.message, "reference": m.reference},
                                   restaurant=request.tenant, reply_to=support,
                                   dedupe_key=f"contact-reply:{m.pk}:{hashlib.sha256(text.encode()).hexdigest()[:24]}")
                if sent is None:
                    raise ValidationError({"text": "This exact reply was already sent."})
                ContactActivity.objects.create(message=m, kind="reply", text=text, author=request.user)
                m.status = ContactMessage.Status.REPLIED
            elif v["action"] == "note":
                ContactActivity.objects.create(message=m, kind="note", text=text, author=request.user)
                if m.status == ContactMessage.Status.NEW:
                    m.status = ContactMessage.Status.IN_PROGRESS
            else:
                if v["status"] == m.status:
                    return Response(message_detail(m))
                m.status = v["status"]
                label = ContactMessage.Status(m.status).label
                ContactActivity.objects.create(message=m, kind="status", text=f"{label}. {text}".strip(), author=request.user)
            m.handled_by = request.user
            m.save(update_fields=["status", "handled_by", "updated_at"])
            audit(f"contact.{v['action']}", actor=request.user, restaurant=request.tenant, obj=m,
                  metadata={"from": before, "to": m.status}, request=request)
        return Response(message_detail(m))


# ---- the platform website's texts and pictures --------------------------------------------------------------------
def _images(request):
    out = {}
    for row in PlatformImage.objects.all():
        try:
            out[row.slot] = request.build_absolute_uri(row.image.url)
        except Exception:  # noqa: BLE001 - a storage hiccup must not break the website
            pass
    return out


class PublicContentView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        row = PlatformContent.objects.filter(pk=1).first()
        stored = row.data if row else {}
        data = content.merged(stored)
        edited = set(stored.get("legal", {}))
        return Response({"content": data, "images": _images(request), "draft_legal": [s for s in data["legal"] if s not in edited]})


class ContentView(APIView):
    permission_classes = [IsPlatformAdminOnPlatformHost]

    def get(self, request):
        row = PlatformContent.load()
        return Response({"content": content.merged(row.data), "changed": {k: sorted(v) for k, v in row.data.items()},
                         "images": _images(request), "slots": HERO_SLOTS, "updated_at": row.updated_at,
                         "updated_by": (row.updated_by.full_name or row.updated_by.email) if row.updated_by else None})

    def patch(self, request):
        """Body: {"<section>": {...fields...}} to save, or {"<section>": null} to go back to the default texts."""
        body = request.data
        if not isinstance(body, dict) or not body:
            raise ValidationError({"detail": "Send the section to save."})
        with transaction.atomic():
            row = PlatformContent.load()
            data = dict(row.data)
            for section, value in body.items():
                if value is None:
                    if section not in content.DEFAULTS:
                        raise ValidationError({section: "Unknown section."})
                    data.pop(section, None)
                    continue
                cleaned = content.clean_section(section, value)
                changes = content.only_changes(section, {**content.merged(data)[section], **cleaned})
                if changes:
                    data[section] = changes
                else:
                    data.pop(section, None)
            row.data, row.updated_by = data, request.user
            row.save()
            audit("platform.website_content_updated", actor=request.user, metadata={"sections": sorted(body)}, request=request)
        return self.get(request)


class HeroUpload(serializers.Serializer):
    image = image_field(HERO_MAX_BYTES)


def _discard(storage, name):
    if not name:
        return
    try:
        storage.delete(name)
    except Exception:  # noqa: BLE001 - an orphaned file is harmless
        pass


class ContentImageView(APIView):
    permission_classes = [IsPlatformAdminOnPlatformHost]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, slot):
        if slot not in HERO_SLOTS:
            raise NotFound()
        s = HeroUpload(data=request.data)
        s.is_valid(raise_exception=True)
        row = PlatformImage.objects.filter(slot=slot).first() or PlatformImage(slot=slot)
        old = row.image.name if row.image else None
        row.image = s.validated_data["image"]
        row.save()
        _discard(row.image.storage, old)
        audit("platform.website_image_updated", actor=request.user, metadata={"slot": slot}, request=request)
        return Response({"images": _images(request)})

    def delete(self, request, slot):
        row = PlatformImage.objects.filter(slot=slot).first()
        if row:
            storage, name = row.image.storage, row.image.name
            row.delete()
            _discard(storage, name)
            audit("platform.website_image_removed", actor=request.user, metadata={"slot": slot}, request=request)
        return Response({"images": _images(request)})
