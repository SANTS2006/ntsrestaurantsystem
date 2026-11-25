from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("tables", views.TableViewSet, basename="dining-table")
router.register("requests", views.RequestViewSet, basename="qr-request")

urlpatterns = [
    path("public/<str:token>/", views.PublicTableView.as_view()),
    path("public/<str:token>/requests/", views.PublicRequestCreateView.as_view()),
    path("public/<str:token>/requests/<uuid:public_id>/", views.PublicRequestStatusView.as_view()),
    path("", include(router.urls)),
]
