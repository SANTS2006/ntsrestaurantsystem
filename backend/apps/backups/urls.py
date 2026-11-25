from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.SystemHealthView.as_view()),
    path("backups/", views.BackupsView.as_view()),
    path("backups/<int:pk>/verify/", views.BackupVerifyView.as_view()),
    path("backups/<int:pk>/restore/", views.BackupRestoreView.as_view()),
    path("restores/", views.RestoresView.as_view()),
]
