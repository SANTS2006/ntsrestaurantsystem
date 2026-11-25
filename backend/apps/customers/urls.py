from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import dashboard, directory, views

router = DefaultRouter()
router.register("addresses", views.AddressViewSet, basename="address")

urlpatterns = [
    path("me/", views.MeView.as_view()),
    path("me/avatar/", views.AvatarView.as_view()),
    path("me/email-change/", views.EmailChangeRequestView.as_view()),
    path("me/email-change/confirm/", views.EmailChangeConfirmView.as_view()),
    path("dashboard/", dashboard.DashboardView.as_view()),
    path("directory/", directory.CustomerList.as_view()),
    path("directory/<int:pk>/", directory.CustomerDetail.as_view()),
    path("", include(router.urls)),
]
