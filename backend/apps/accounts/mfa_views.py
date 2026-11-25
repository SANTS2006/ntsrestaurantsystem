from django.contrib.auth import authenticate
from rest_framework import serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.models import audit

from . import mfa, services
from .models import Membership, Role, User
from .permissions import IsPlatformAdmin
from .views import err


def _password_ok(request):
    return authenticate(request, username=request.user.email, password=str(request.data.get("password", ""))) is not None


class MfaView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class StatusView(MfaView):
    def get(self, request):
        u = request.user
        return Response({"success": True, "data": {"enabled": u.mfa_enabled, "required": mfa.required_for(u), "recovery_codes_left": mfa.recovery_left(u) if u.mfa_enabled else 0}})


class SetupView(MfaView):
    """Start enrolment: needs the current password; returns the secret and a QR code to scan. Nothing is active until /confirm/."""

    def post(self, request):
        if not _password_ok(request):
            return err("invalid_password", "Your current password is not correct.", 403)
        if request.user.mfa_enabled:
            return err("already_enabled", "Two-factor authentication is already on. Turn it off first to enrol a new device.", 400)
        data = mfa.begin_setup(request.user)
        audit("auth.mfa_setup_started", actor=request.user, request=request)
        return Response({"success": True, "data": data})


class ConfirmView(MfaView):
    def post(self, request):
        if mfa.locked(request.user):
            return err("locked", "Too many attempts. Try again later.", 429)
        codes = mfa.confirm_setup(request.user, str(request.data.get("code", "")))
        if codes is None:
            mfa._record_fail(request.user)
            audit("auth.mfa_confirm_failed", actor=request.user, request=request)
            return err("invalid_code", "That code is not correct. Check your device clock and try again.", 400)
        audit("auth.mfa_enabled", actor=request.user, request=request)
        # new tokens carry the "second factor enrolled" claim, which lifts the enrolment gate without a new login
        return Response({"success": True, "data": {"recovery_codes": codes, **services.issue_tokens(request.user)}})


class VerifyView(APIView):
    """Second step of sign-in: trade the short-lived token from the password step plus a code for the real session."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        user = mfa.user_from_login_token(str(request.data.get("mfa_token", "")))
        if user is None:
            return err("invalid_token", "Your sign-in expired. Please sign in again.", 401)
        ok, how = mfa.verify(user, str(request.data.get("code", "")), str(request.data.get("recovery_code", "")))
        if not ok:
            audit("auth.mfa_failed", actor=user, restaurant=request.tenant, metadata={"reason": how}, request=request)
            if how == "locked":
                return err("locked", "Too many attempts. Try again later.", 429)
            return err("invalid_code", "That code is not correct.", 401)
        audit("auth.login", actor=user, restaurant=request.tenant, metadata={"mfa": how}, request=request)
        if how == "recovery":
            audit("auth.mfa_recovery_used", actor=user, restaurant=request.tenant, metadata={"left": mfa.recovery_left(user)}, request=request)
        return Response({"success": True, "data": {**services.issue_tokens(user), "must_change_password": user.must_change_password, "recovery_codes_left": mfa.recovery_left(user)}})


class DisableView(MfaView):
    def post(self, request):
        u = request.user
        if not u.mfa_enabled:
            return err("not_enabled", "Two-factor authentication is not on.", 400)
        if mfa.required_for(u):
            return err("required", "Your role requires two-factor authentication, so it cannot be turned off.", 403)
        if not _password_ok(request):
            return err("invalid_password", "Your current password is not correct.", 403)
        ok, _ = mfa.verify(u, str(request.data.get("code", "")), str(request.data.get("recovery_code", "")))
        if not ok:
            return err("invalid_code", "That code is not correct.", 400)
        mfa.disable(u)
        audit("auth.mfa_disabled", actor=u, request=request)
        return Response({"success": True, "data": {"enabled": False}})


class RecoveryCodesView(MfaView):
    """Replace all recovery codes (shown once). Needs the password and a current code."""

    def post(self, request):
        u = request.user
        if not u.mfa_enabled:
            return err("not_enabled", "Two-factor authentication is not on.", 400)
        if not _password_ok(request):
            return err("invalid_password", "Your current password is not correct.", 403)
        ok, how = mfa.verify(u, str(request.data.get("code", "")))
        if not ok:
            return err("invalid_code", "That code is not correct.", 400)
        audit("auth.mfa_recovery_regenerated", actor=u, request=request)
        return Response({"success": True, "data": {"recovery_codes": mfa.new_recovery_codes(u)}})


class AdminResetView(APIView):
    """Lost authenticator: a platform administrator resets another account's second factor (the user must enrol again).
    A platform administrator's own factor is reset by an operator with `manage.py mfa_reset`."""

    permission_classes = [IsPlatformAdmin]

    def post(self, request, user_id):
        target = User.objects.filter(pk=user_id).first()
        if target is None or target.pk == request.user.pk:
            return err("not_found", "No such user.", 404)
        if target.is_platform_admin:
            return err("forbidden", "Platform administrators are reset by an operator.", 403)
        if not Membership.objects.filter(user=target, role__in=[Role.RESTAURANT_ADMIN, Role.MANAGER, Role.CASHIER, Role.KITCHEN, Role.WAITER, Role.WAITRESS, Role.DELIVERY]).exists():
            return err("not_found", "No such staff user.", 404)
        mfa.disable(target)
        audit("auth.mfa_reset_by_admin", actor=request.user, metadata={"user": target.pk}, request=request)
        return Response({"success": True, "data": {"reset": True}})


_ = serializers
