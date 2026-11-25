from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("branches", views.BranchViewSet, basename="branch")

urlpatterns = [
    path("current/", views.CurrentRestaurantView.as_view()),
    path("", include(router.urls)),
]
