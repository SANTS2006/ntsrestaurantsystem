from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.catalog import seo as seo_views
from apps.core import views as core_views

from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("healthz", core_views.liveness),
    path("readyz", core_views.readiness),
    path("django-admin/", admin.site.urls),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/restaurants/", include("apps.tenants.urls")),
    path("api/v1/platform/", include("apps.tenants.platform_urls")),
    path("api/v1/catalog/", include("apps.catalog.urls")),
    path("api/v1/customers/", include("apps.customers.urls")),
    path("api/v1/orders/", include("apps.orders.urls")),
    path("api/v1/payments/", include("apps.payments.urls")),
    path("api/v1/cashier/", include("apps.cashier.urls")),
    path("api/v1/reports/", include("apps.reports.urls")),
    path("api/v1/qr-menu/", include("apps.qrmenu.urls")),
    path("api/v1/catering/", include("apps.catering.urls")),
    path("api/v1/payroll/", include("apps.payroll.urls")),
    path("api/v1/system/", include("apps.backups.urls")),
    path("api/v1/finance/", include("apps.finance.urls")),
    path("api/v1/procurement/", include("apps.procurement.urls")),
    path("api/v1/floor/", include("apps.floor.urls")),
    path("robots.txt", seo_views.robots_txt),
    path("sitemap.xml", seo_views.sitemap_xml),
    path("api/v1/staff/", include("apps.accounts.staff_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:  # API documentation is not published in production
    urlpatterns += [path("api/schema/", SpectacularAPIView.as_view(), name="schema"), path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"))]

# Everything that is not the API, a WebSocket, the admin or a static file is a page of the React app.
from apps.core.spa import spa  # noqa: E402

urlpatterns += [re_path(r"^(?!api/|ws/|django-admin/|static/|media/|healthz|readyz)(?P<path>.*)$", spa)]
handler404 = "apps.core.views.not_found"
