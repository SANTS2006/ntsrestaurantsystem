from django.urls import path

from . import views as v

urlpatterns = [
    path("summary/", v.SummaryView.as_view()),
    path("suppliers/", v.SuppliersView.as_view()),
    path("suppliers/<int:pk>/", v.SupplierView.as_view()),
    path("ingredients/", v.IngredientsView.as_view()),
    path("ingredients/<int:pk>/", v.IngredientView.as_view()),
    path("stock/adjust/", v.AdjustView.as_view()),
    path("stock/movements/", v.MovementsView.as_view()),
    path("products/<int:product_id>/recipe/", v.RecipeView.as_view()),
    path("orders/", v.POListView.as_view()),
    path("orders/<int:pk>/", v.PODetailView.as_view()),
    path("orders/<int:pk>/<str:act>/", v.POActionView.as_view()),
]
