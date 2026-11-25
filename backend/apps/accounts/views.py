from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.models import audit

from . import mfa, services
from .google import GoogleAuthError
from .models import Role, User
from .permissions import IsManagerOrAbove, accessible_branch_ids, effective_role

MAX_FAILED = 5
LOCK_SECONDS = 15 * 60


def err(code, message, status, details=None):
    return Response({"success": False, "error": {"code": code, "message": message, "details": details}}, status=status)


GENERIC_FAIL = {"success": False, "error": {"code": "invalid_credentials", "message": "Invalid email or password."}}
ACCEPTED = {"success": True, "data": {"message": "If the details are valid, an email has been sent."}}


def _fail_key(email):
    return f"login-fail:{email.lower()}"


class AnonAuthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        email, password = s.validated_data["email"].lower(), s.validated_data["password"]

        if cache.get(_fail_key(email), 0) >= MAX_FAILED:
            audit("auth.login_locked", restaurant=request.tenant, metadata={"email": email}, request=request)
            return err("locked", "Too many attempts. Try again later.", 429)

        user = authenticate(request, username=email, password=password)
        if not (user and user.is_active and self._may_use_host(request, user)):
            cache.set(_fail_key(email), cache.get(_fail_key(email), 0) + 1, LOCK_SECONDS)
            audit("auth.login_failed", restaurant=request.tenant, metadata={"email": email}, request=request)
            return Response(GENERIC_FAIL, status=401)  # same response for every failure reason

        # Password is proven from here on, so revealing account state is safe.
        if not user.email_verified:
            return err("email_not_verified", "Please verify your email address before signing in.", 403)
        if user.must_change_password and user.temp_password_expires_at and user.temp_password_expires_at < timezone.now():
            return Response(GENERIC_FAIL, status=401)  # expired bootstrap credential

        cache.delete(_fail_key(email))
        if user.mfa_enabled:  # password alone never yields a session for an account with a second factor
            audit("auth.login_mfa_required", actor=user, restaurant=request.tenant, request=request)
            return Response({"success": True, "data": {"mfa_required": True, "mfa_token": mfa.login_token(user)}})
        audit("auth.login", actor=user, restaurant=request.tenant, request=request)
        return Response({"success": True, "data": {**services.issue_tokens(user),
                                                   "must_change_password": user.must_change_password}})

    @staticmethod
    def _may_use_host(request, user):
        if request.is_platform:
            return user.is_platform_admin
        return user.is_platform_admin or user.memberships.filter(restaurant=request.tenant, is_active=True).exists()


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        return Response({"success": True, "data": {
            "id": u.pk, "email": u.email, "full_name": u.full_name,
            "role": effective_role(request),  # derived server-side for display only
            "branch_ids": sorted(accessible_branch_ids(request)),
            "must_change_password": u.must_change_password,
            "mfa": {"enabled": u.mfa_enabled, "required": mfa.required_for(u), "enforced": mfa.enforced()},
        }})


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        current, new = request.data.get("current_password", ""), request.data.get("new_password", "")
        user: User = request.user
        if not user.check_password(current):
            return err("invalid_password", "Current password is incorrect.", 400)
        try:
            validate_password(new, user)
        except DjangoValidationError as exc:
            return err("weak_password", "Password too weak.", 400, list(exc.messages))
        if user.check_password(new):
            return err("same_password", "New password must differ from the current one.", 400)
        services.set_new_password(request, user, new)
        return Response({"success": True, "data": services.issue_tokens(user)})  # old tokens are now revoked


# ---- registration / verification ---------------------------------------------------------------
class RegisterSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    accept_terms = serializers.BooleanField()

    def validate_accept_terms(self, value):
        if value is not True:
            raise serializers.ValidationError("You must agree to the Terms of Service and Privacy Policy.")
        return value

    def validate(self, attrs):
        try:
            validate_password(attrs["password"], User(email=attrs["email"], full_name=attrs["full_name"]))
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs


class RegisterView(AnonAuthView):
    def post(self, request):
        s = RegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            services.register_customer(request, email=d["email"], full_name=d["full_name"], phone=d["phone"], password=d["password"])
        except services.FlowError as e:
            return err(e.code, e.message, e.status)
        return Response(ACCEPTED, status=202)  # identical whether or not the email already existed


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()


class VerifyEmailSerializer(EmailSerializer):
    code = serializers.CharField(max_length=10)


class VerifyEmailView(AnonAuthView):
    def post(self, request):
        s = VerifyEmailSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            services.verify_email(request, s.validated_data["email"], s.validated_data["code"])
        except services.FlowError as e:
            return err(e.code, e.message, e.status)
        return Response({"success": True})


class ResendVerificationView(AnonAuthView):
    def post(self, request):
        s = EmailSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        services.resend_verification(request, s.validated_data["email"])
        return Response(ACCEPTED, status=202)


class PasswordResetRequestView(AnonAuthView):
    def post(self, request):
        s = EmailSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        services.request_password_reset(request, s.validated_data["email"])
        return Response(ACCEPTED, status=202)


class PasswordResetConfirmSerializer(VerifyEmailSerializer):
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)


class PasswordResetConfirmView(AnonAuthView):
    def post(self, request):
        s = PasswordResetConfirmSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            services.confirm_password_reset(request, d["email"], d["code"], d["new_password"])
        except DjangoValidationError as exc:
            return err("weak_password", "Password too weak.", 400, list(exc.messages))
        except services.FlowError as e:
            return err(e.code, e.message, e.status)
        return Response({"success": True})


class SetupPasswordView(AnonAuthView):
    def post(self, request):
        try:
            services.accept_setup(request, request.data.get("token", ""), request.data.get("password", ""))
        except DjangoValidationError as exc:
            return err("weak_password", "Password too weak.", 400, list(exc.messages))
        except services.FlowError as e:
            return err(e.code, e.message, e.status)
        return Response({"success": True})


class GoogleLoginView(AnonAuthView):
    def post(self, request):
        try:
            user = services.google_login(request, request.data.get("id_token", ""), request.data.get("accept_terms") is True)
        except GoogleAuthError:
            return err("invalid_google_token", "Google sign-in failed.", 401)
        except services.FlowError as e:
            return err(e.code, e.message, e.status)
        if user.mfa_enabled:
            return Response({"success": True, "data": {"mfa_required": True, "mfa_token": mfa.login_token(user)}})
        return Response({"success": True, "data": {**services.issue_tokens(user), "must_change_password": False}})


# ---- staff invitations -------------------------------------------------------------------------
class StaffInviteSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    role = serializers.ChoiceField(choices=[r for r in Role.values if r not in (Role.PLATFORM_ADMIN, Role.CUSTOMER)])
    branch_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)


class StaffInvitationView(APIView):
    permission_classes = [IsManagerOrAbove]

    def post(self, request):
        s = StaffInviteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            m = services.invite_staff(request, **s.validated_data)
        except services.FlowError as e:
            return err(e.code, e.message, e.status)
        return Response({"success": True, "data": {"membership_id": m.pk, "role": m.role}}, status=201)
