from django.urls import path

from . import views

urlpatterns = [
    path("branch/", views.BranchReportView.as_view()),
    path("export/", views.ExportView.as_view()),
    path("finance/", views.FinanceReportView.as_view()),
    path("finance/export/", views.FinanceExportView.as_view()),
    path("analytics/", views.AnalyticsView.as_view()),
    path("audit/", views.TenantAuditView.as_view()),
    path("platform/", views.PlatformReportView.as_view()),
]
