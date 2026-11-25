"""The signed-in person's own profile (every role, platform or restaurant): name, phone, picture, and a verified e-mail change."""
import re

from django.db import transaction
from rest_framework import serializers
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.models import audit
from apps.core.uploads import image_field
from apps.notifications.services import queue_email

from . import services
from .codes import consume_code, issue_code
from .models import OneTimeCode, User
from .permissions import effective_role


def profile_json(request):
    u = request.user
    return {"id": u.pk, "email": u.email, "full_name": u.full_name, "phone": u.phone, "role": effective_role(request),
            "avatar": request.build_absolute_uri(u.avatar.url) if u.avatar else None, "email_verified": u.email_verified}


def _bad(code, message, status=400):
    return Response({"success": False, "error": {"code": code, "message": message}}, status=status)


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"success": True, "data": profile_json(request)})

    def patch(self, request):
        class S(serializers.Serializer):
            full_name = serializers.CharField(max_length=150, required=False, allow_blank=False)
            phone = serializers.RegexField(r"^[0-9+()\-\s]{6,30}$", required=False, allow_blank=True)

        s = S(data=request.data)
        s.is_valid(raise_exception=True)
        fields = [k for k in ("full_name", "phone") if k in s.validated_data]
        for k in fields:
            setattr(request.user, k, s.validated_data[k].strip())
        if fields:
            request.user.save(update_fields=fields)
            audit("auth.profile_updated", actor=request.user, restaurant=getattr(request, "tenant", None), metadata={"fields": fields}, request=request)
        return Response({"success": True, "data": profile_json(request)})


class AvatarSerializer(serializers.Serializer):
    image = image_field(2 * 1024 * 1024)  # checked, scanned and re-encoded: see apps.core.uploads


class AvatarView(APIView):
    """Upload or replace (POST) and remove (DELETE) the profile picture."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        s = AvatarSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        old = request.user.avatar
        request.user.avatar = s.validated_data["image"]
        request.user.save(update_fields=["avatar"])
        if old:
            old.delete(save=False)  # replaced pictures are not kept
        return Response({"success": True, "data": profile_json(request)})

    def delete(self, request):
        if request.user.avatar:
            request.user.avatar.delete(save=False)
            request.user.avatar = ""
            request.user.save(update_fields=["avatar"])
        return Response({"success": True, "data": profile_json(request)})


class EmailChangeRequestView(APIView):
    """Step 1: send a code to the NEW address (needs the current password)."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        new = str(request.data.get("new_email", "")).strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", new) or len(new) > 254:
            return _bad("invalid_email", "Enter a valid email address.")
        if not request.user.check_password(str(request.data.get("password", ""))):
            return _bad("invalid_password", "Your password is not correct.")
        # Same answer whether or not the address is taken, so this cannot be used to discover accounts.
        if new != request.user.email and not User.objects.filter(email__iexact=new).exists():
            code = issue_code(request.user, OneTimeCode.Purpose.EMAIL_CHANGE, getattr(request, "tenant", None), payload=new)
            if code:
                queue_email("verify_email", new, {"name": request.user.full_name, "code": code}, restaurant=getattr(request, "tenant", None))
        return Response({"success": True, "data": {"message": "If the address can be used, a code has been sent to it."}}, status=202)


class EmailChangeConfirmView(APIView):
    """Step 2: the code proves the new mailbox is theirs; the address changes and other sessions end."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        record = consume_code(request.user, OneTimeCode.Purpose.EMAIL_CHANGE, str(request.data.get("code", "")))
        if not record:
            return _bad("invalid_code", "Invalid or expired code.")
        new = record.payload
        with transaction.atomic():
            if User.objects.filter(email__iexact=new).exclude(pk=request.user.pk).exists():
                return _bad("invalid_code", "Invalid or expired code.")
            old = request.user.email
            request.user.email = new
            request.user.email_verified = True
            request.user.save(update_fields=["email", "email_verified"])
            services.revoke_tokens(request.user)
            audit("auth.email_changed", actor=request.user, restaurant=getattr(request, "tenant", None), metadata={"old": old}, request=request)
            queue_email("email_changed", old, {"name": request.user.full_name, "new_email": new}, restaurant=getattr(request, "tenant", None))
        return Response({"success": True, "data": services.issue_tokens(request.user)})
