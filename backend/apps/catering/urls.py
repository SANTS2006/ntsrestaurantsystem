from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("requests", views.CateringViewSet, basename="catering-request")

urlpatterns = [
    path("public/options/", views.PublicOptionsView.as_view()),
    path("public/requests/", views.PublicSubmitView.as_view()),
    path("public/quotations/<str:token>/", views.PublicQuotationView.as_view()),
    path("public/quotations/<str:token>/accept/", views.PublicQuotationRespondView.as_view()),
    path("public/quotations/<str:token>/decline/", views.PublicQuotationDeclineView.as_view()),
    path("", include(router.urls)),
]
