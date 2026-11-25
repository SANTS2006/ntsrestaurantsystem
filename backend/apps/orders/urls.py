from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("my", views.MyOrderViewSet, basename="my-order")
router.register("manage", views.StaffOrderViewSet, basename="staff-order")

urlpatterns = [
    path("quote/", views.QuoteView.as_view()),
    path("checkout/", views.CheckoutView.as_view()),
    path("", include(router.urls)),
]
