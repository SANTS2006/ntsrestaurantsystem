from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("shifts", views.ShiftViewSet, basename="shift")

urlpatterns = [
    path("dashboard/", views.DashboardView.as_view()),
    path("orders/", views.CashierOrderView.as_view()),
    path("quote/", views.CashierQuoteView.as_view()),
    path("shift/current/", views.CurrentShiftView.as_view()),
    path("shift/open/", views.OpenShiftView.as_view()),
    path("shifts/<int:pk>/close/", views.CloseShiftView.as_view()),
    path("shifts/<int:pk>/adjustments/", views.RequestAdjustmentView.as_view()),
    path("adjustments/pending/", views.PendingAdjustmentsView.as_view()),
    path("adjustments/<int:pk>/decide/", views.DecideAdjustmentView.as_view()),
    path("", include(router.urls)),
]
