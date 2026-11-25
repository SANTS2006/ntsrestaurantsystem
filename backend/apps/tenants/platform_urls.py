from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import platform_views as v

router = DefaultRouter()
router.register("restaurants", v.PlatformRestaurantViewSet, basename="platform-restaurant")
router.register("plans", v.SubscriptionPlanViewSet, basename="platform-plan")
router.register("audit-logs", v.AuditLogViewSet, basename="platform-audit")

urlpatterns = [
    path("public/settings/", v.PublicSettingsView.as_view()),
    path("public/plans/", v.PublicPlansView.as_view()),
    path("settings/", v.PlatformSettingsView.as_view()),
    path("dashboard/", v.PlatformDashboardView.as_view()),
    path("", include(router.urls)),
]
