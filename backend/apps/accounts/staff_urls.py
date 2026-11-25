from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import staff_views, views

router = DefaultRouter()
router.register("members", staff_views.StaffViewSet, basename="staff-member")

urlpatterns = [
    path("invitations/", views.StaffInvitationView.as_view()),
    path("", include(router.urls)),
]
