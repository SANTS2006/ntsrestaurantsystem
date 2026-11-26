from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("manage", views.StaffPaymentViewSet, basename="staff-payment")

urlpatterns = [
    path("initiate/", views.InitiateView.as_view()),
    path("my/<int:pk>/", views.MyPaymentStatusView.as_view()),
    path("cash/", views.CashView.as_view()),
    path("mobile-money/", views.StaffMobileMoneyView.as_view()),
    path("<int:pk>/status/", views.StaffPaymentStatusView.as_view()),
    path("<int:pk>/refund/", views.RefundView.as_view()),
    path("receipts/<int:pk>/", views.ReceiptView.as_view()),
    path("receipts/<int:pk>/pdf/", views.ReceiptPdfView.as_view()),
    path("webhooks/<slug:provider_name>/", views.WebhookView.as_view()),
    path("dev/simulate/", views.SimulateView.as_view()),
    path("", include(router.urls)),
]
