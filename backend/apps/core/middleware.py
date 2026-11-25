"""Tenant resolution from the validated request hostname.

* Platform hosts (PLATFORM_HOSTS)            -> request.tenant = None, request.is_platform = True
* <slug>.<PLATFORM_DOMAIN>                   -> restaurant by slug
* any other host                             -> verified RestaurantDomain (custom domains)
Unknown hosts get 404; suspended restaurants get 403. The tenant is never read from a header or
a client-supplied body field.
"""
from django.conf import settings
from django.http import JsonResponse

from .tenancy import reset_current_tenant, set_current_tenant

EXEMPT_PREFIXES = ("/healthz", "/readyz")


def _deny(status, code, message):
    return JsonResponse({"success": False, "error": {"code": code, "message": message}}, status=status)


def resolve_host(host):
    """Return (is_platform, restaurant_or_None, found)."""
    from apps.tenants.models import Restaurant, RestaurantDomain

    host = host.split(":")[0].lower().rstrip(".")
    if host in settings.PLATFORM_HOSTS:
        return True, None, True
    suffix = "." + settings.PLATFORM_DOMAIN
    if host.endswith(suffix):
        slug = host[: -len(suffix)]
        if "." not in slug:
            restaurant = Restaurant.unscoped_objects.filter(slug=slug).first()
            return False, restaurant, restaurant is not None
    domain = RestaurantDomain.objects.select_related("restaurant").filter(hostname=host, is_verified=True).first()
    return False, (domain.restaurant if domain else None), domain is not None


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None
        request.is_platform = False
        if request.path.startswith(EXEMPT_PREFIXES) or request.path.startswith("/django-admin"):
            return self.get_response(request)

        is_platform, restaurant, found = resolve_host(request.get_host())
        if not found:
            return _deny(404, "unknown_host", "Unknown host.")
        if restaurant is not None and restaurant.status != "active":
            return _deny(403, "restaurant_suspended", "This restaurant is currently unavailable.")
        request.is_platform, request.tenant = is_platform, restaurant
        token = set_current_tenant(restaurant)
        try:
            return self.get_response(request)
        finally:
            reset_current_tenant(token)


class MaintenanceMiddleware:
    """While a platform restore is running every request except the health checks gets a 503 (clients retry later)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith(EXEMPT_PREFIXES):
            from django.core.cache import cache

            if cache.get("platform-maintenance"):
                resp = _deny(503, "maintenance", "The platform is being restored from a backup. Please try again in a few minutes.")
                resp["Retry-After"] = "120"
                return resp
        return self.get_response(request)
