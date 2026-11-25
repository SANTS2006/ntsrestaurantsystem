from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import mfa_views, views

urlpatterns = [
    path("login/", views.LoginView.as_view()),
    path("google/", views.GoogleLoginView.as_view()),
    path("token/refresh/", TokenRefreshView.as_view()),
    path("me/", views.MeView.as_view()),
    path("change-password/", views.ChangePasswordView.as_view()),
    path("register/", views.RegisterView.as_view()),
    path("verify-email/", views.VerifyEmailView.as_view()),
    path("resend-verification/", views.ResendVerificationView.as_view()),
    path("password-reset/", views.PasswordResetRequestView.as_view()),
    path("password-reset/confirm/", views.PasswordResetConfirmView.as_view()),
    path("setup-password/", views.SetupPasswordView.as_view()),
    path("mfa/status/", mfa_views.StatusView.as_view()),
    path("mfa/setup/", mfa_views.SetupView.as_view()),
    path("mfa/confirm/", mfa_views.ConfirmView.as_view()),
    path("mfa/verify/", mfa_views.VerifyView.as_view()),
    path("mfa/disable/", mfa_views.DisableView.as_view()),
    path("mfa/recovery-codes/", mfa_views.RecoveryCodesView.as_view()),
    path("mfa/reset/<int:user_id>/", mfa_views.AdminResetView.as_view()),
]
