from django.urls import path

from . import views as v

urlpatterns = [
    path("settings/", v.SettingsView.as_view()),
    path("employees/", v.EmployeesView.as_view()),
    path("structures/", v.StructuresView.as_view()),
    path("structures/<int:pk>/<str:act>/", v.StructureActionView.as_view()),
    path("periods/", v.PeriodsView.as_view()),
    path("periods/<int:pk>/", v.PeriodDetailView.as_view()),
    path("periods/<int:pk>/generate/", v.PeriodGenerateView.as_view()),
    path("periods/<int:pk>/records/", v.PeriodRecordView.as_view()),
    path("periods/<int:pk>/candidates/", v.PeriodCandidatesView.as_view()),
    path("periods/<int:pk>/bulk/", v.PeriodBulkView.as_view()),
    path("records/<int:pk>/", v.RecordView.as_view()),
    path("records/<int:pk>/pdf/", v.RecordPdfView.as_view()),
    path("records/<int:pk>/<str:act>/", v.RecordActionView.as_view()),
    path("summary/", v.SummaryView.as_view()),
    path("export.csv", v.ExportView.as_view()),
    path("me/", v.MyPayView.as_view()),
    path("me/records/<int:pk>/pdf/", v.MyPdfView.as_view()),
]
