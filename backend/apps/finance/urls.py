from django.urls import path

from . import views as v

urlpatterns = [
    path("categories/", v.CategoriesView.as_view()),
    path("expenses/", v.ExpensesView.as_view()),
    path("expenses/<int:pk>/void/", v.ExpenseVoidView.as_view()),
    path("invoices/", v.InvoicesView.as_view()),
    path("invoices/<int:pk>/", v.InvoiceView.as_view()),
    path("invoices/<int:pk>/pdf/", v.InvoicePdfView.as_view()),
    path("invoices/<int:pk>/<str:act>/", v.InvoiceActionView.as_view()),
]
