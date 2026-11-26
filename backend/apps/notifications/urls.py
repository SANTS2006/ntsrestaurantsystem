from django.urls import path

from . import views

urlpatterns = [
    path("", views.NotificationsView.as_view()),
    path("<int:pk>/", views.NotificationDetailView.as_view()),
    path("read/", views.MarkReadView.as_view()),
    path("clear/", views.ClearView.as_view()),
]
