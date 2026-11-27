from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import public_views as pv
from . import views

router = DefaultRouter()
router.register("categories", views.CategoryViewSet, basename="category")
router.register("products", views.ProductViewSet, basename="product")
router.register("stock-movements", views.StockMovementViewSet, basename="stock-movement")
router.register("services", views.ServiceViewSet, basename="service")
router.register("gallery", views.GalleryViewSet, basename="gallery")

urlpatterns = [
    path("public/menu/", pv.PublicMenuView.as_view()),
    path("public/products/<slug:slug>/", pv.PublicProductView.as_view()),
    path("public/services/", pv.PublicServicesView.as_view()),
    path("public/gallery/", pv.PublicGalleryView.as_view()),
    path("public/site/", pv.PublicSiteView.as_view()),
    path("public/policies/<slug:slug>/", pv.PublicPolicyView.as_view()),
    path("site/", pv.SiteContentView.as_view()),
    path("site/hero/", pv.SiteHeroView.as_view()),
    path("", include(router.urls)),
]
