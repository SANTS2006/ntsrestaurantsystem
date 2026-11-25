import re

from django.db import transaction
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts import services as auth_services
from apps.accounts.codes import consume_code, issue_code
from apps.accounts.models import OneTimeCode, User
from apps.accounts.permissions import IsCustomerOfTenant, get_membership
from apps.core.models import audit
from apps.core.uploads import image_field
from apps.notifications.services import queue_email

from .models import CustomerAddress

MAX_ADDRESSES = 10
DEFAULT_PREFS = {"order_emails": True, "promotions": False}


def prefs_of(membership):
    return {**DEFAULT_PREFS, **(membership.preferences or {})}


class CustomerBase(APIView):
    permission_classes = [IsAuthenticated, IsCustomerOfTenant]


def profile_data(request):
    u = request.user
    return {"id": u.pk, "email": u.email, "full_name": u.full_name, "phone": u.phone,
            "avatar": request.build_absolute_uri(u.avatar.url) if u.avatar else None,
            "email_verified": u.email_verified, "preferences": prefs_of(get_membership(request))}


class ProfileSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150, required=False, allow_blank=False)
    phone = serializers.RegexField(r"^[0-9+()\-\s]{6,30}$", required=False, allow_blank=True)
    preferences = serializers.DictField(child=serializers.BooleanField(), required=False)

    def validate_preferences(self, value):
        if set(value) - set(DEFAULT_PREFS):
            raise serializers.ValidationError("Unknown preference.")
        return value


class MeView(CustomerBase):
    def get(self, request):
        return Response(profile_data(request))

    def patch(self, request):
        s = ProfileSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        d, u, m = s.validated_data, request.user, get_membership(request)
        for k in ("full_name", "phone"):
            if k in d:
                setattr(u, k, d[k])
        u.save(update_fields=[k for k in ("full_name", "phone") if k in d] or None)
        if "preferences" in d:
            m.preferences = {**prefs_of(m), **d["preferences"]}
            m.save(update_fields=["preferences"])
        return Response(profile_data(request))


class AvatarSerializer(serializers.Serializer):
    image = image_field(2 * 1024 * 1024)


class AvatarView(CustomerBase):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        s = AvatarSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        request.user.avatar = s.validated_data["image"]
        request.user.save(update_fields=["avatar"])
        return Response(profile_data(request))

    def delete(self, request):
        request.user.avatar.delete(save=False)
        request.user.avatar = ""
        request.user.save(update_fields=["avatar"])
        return Response(profile_data(request))


# ---- verified email change ---------------------------------------------------------------------
class EmailChangeSerializer(serializers.Serializer):
    new_email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class EmailChangeRequestView(CustomerBase):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        s = EmailChangeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        new = s.validated_data["new_email"].lower()
        if not request.user.check_password(s.validated_data["password"]):  # re-authenticate for a sensitive change
            return Response({"success": False, "error": {"code": "invalid_password", "message": "Password is incorrect."}}, status=400)
        # Identical response whether or not the address is taken (no enumeration); the code goes only to the new mailbox.
        if new != request.user.email and not User.objects.filter(email__iexact=new).exists():
            code = issue_code(request.user, OneTimeCode.Purpose.EMAIL_CHANGE, request.tenant, payload=new)
            if code:
                queue_email("verify_email", new, {"name": request.user.full_name, "code": code}, restaurant=request.tenant)
        return Response({"success": True, "data": {"message": "If the address can be used, a code has been sent to it."}}, status=202)


class EmailChangeConfirmView(CustomerBase):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        record = consume_code(request.user, OneTimeCode.Purpose.EMAIL_CHANGE, str(request.data.get("code", "")))
        new = record.payload if record else ""
        fail = Response({"success": False, "error": {"code": "invalid_code", "message": "Invalid or expired code."}}, status=400)
        if not record:
            return fail
        with transaction.atomic():
            if User.objects.filter(email__iexact=new).exclude(pk=request.user.pk).exists():
                return fail
            old = request.user.email
            request.user.email = new
            request.user.email_verified = True
            request.user.save(update_fields=["email", "email_verified"])
            auth_services.revoke_tokens(request.user)
            audit("auth.email_changed", actor=request.user, restaurant=request.tenant, metadata={"old": old}, request=request)
            queue_email("email_changed", old, {"name": request.user.full_name, "new_email": new}, restaurant=request.tenant)
        return Response({"success": True, "data": auth_services.issue_tokens(request.user)})  # old tokens are revoked


# ---- addresses ---------------------------------------------------------------------------------
class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerAddress
        fields = ["id", "label", "recipient_name", "phone", "line1", "line2", "city", "delivery_notes", "is_default"]
        read_only_fields = ["id"]

    def validate_phone(self, v):
        if v and not re.fullmatch(r"[0-9+()\-\s]{6,30}", v):
            raise serializers.ValidationError("Enter a valid phone number.")
        return v


class AddressViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsCustomerOfTenant]
    serializer_class = AddressSerializer
    pagination_class = None

    def get_queryset(self):  # only the caller's own addresses within this restaurant: no IDOR
        return CustomerAddress.unscoped.filter(restaurant=self.request.tenant, user=self.request.user)

    @transaction.atomic
    def perform_create(self, serializer):
        mine = self.get_queryset()
        if mine.count() >= MAX_ADDRESSES:
            raise serializers.ValidationError({"detail": f"You can save up to {MAX_ADDRESSES} addresses."})
        make_default = serializer.validated_data.get("is_default") or not mine.exists()
        if make_default:
            mine.update(is_default=False)
        serializer.save(restaurant=self.request.tenant, user=self.request.user, is_default=make_default)

    @transaction.atomic
    def perform_update(self, serializer):
        if serializer.validated_data.get("is_default"):
            self.get_queryset().exclude(pk=serializer.instance.pk).update(is_default=False)
        serializer.save()

    @action(detail=False, methods=["get"], url_path="count")
    def count(self, request):
        return Response({"count": self.get_queryset().count()})

