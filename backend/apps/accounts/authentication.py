from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication

# A privileged account that has not enrolled two-factor authentication may only reach these endpoints (to enrol, see itself, or leave).
MFA_ENROLMENT_ALLOWED = ("/api/v1/auth/me/", "/api/v1/auth/mfa/", "/api/v1/auth/change-password/", "/api/v1/auth/token/refresh/")


class VersionedJWTAuthentication(JWTAuthentication):
    """Rejects tokens issued before the user's last password change/reset (token revocation), and keeps privileged accounts
    without a second factor away from everything except enrolment."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        _, token = result
        if getattr(settings, "MFA_ENFORCEMENT", False) and token.get("mp") and not token.get("mf") and not request.path.startswith(MFA_ENROLMENT_ALLOWED):
            raise PermissionDenied("Two-factor authentication must be set up before you can continue.", code="mfa_enrollment_required")
        return result

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if validated_token.get("tv") != user.token_version:
            raise AuthenticationFailed("Token has been revoked.", code="token_revoked")
        return user
