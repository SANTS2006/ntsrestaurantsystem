"""Tenant resolution from the validated request hostname.

* Platform hosts (PLATFORM_HOSTS), path /<slug>/...  -> restaurant by slug; the slug is stripped from `path_info`
  so every route works unchanged (`/alpha/api/v1/orders/` is served as `/api/v1/orders/` for restaurant alpha)
* Platform hosts, any other path                    -> request.tenant = None, request.is_platform = True
* any other host                                    -> verified RestaurantDomain (an optional custom domain)
There is no wildcard-subdomain routing. Unknown hosts get 404; suspended restaurants get 403. The tenant is never read from a
header or a client-supplied body field; the slug in the URL path is public (like a hostname) and every permission is still checked
against the user's membership of that restaurant.
"""
from django.conf import settings
from django.http import JsonResponse

from .tenancy import reset_current_tenant, set_current_tenant

EXEMPT_PREFIXES = ("/healthz", "/readyz")


def _deny(status, code, message):
    return JsonResponse({"success": False, "error": {"code": code, "message": message}}, status=status)


def resolve_host(host):
    """Return (is_platform, restaurant_or_None, found) for the hostname alone (platform host or verified custom domain)."""
    from apps.tenants.models import RestaurantDomain

    host = host.split(":")[0].lower().rstrip(".")
    if host in settings.PLATFORM_HOSTS:
        return True, None, True
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
        if is_platform:
            restaurant = self._restaurant_from_path(request)
            is_platform = restaurant is None
        if restaurant is not None and restaurant.status != "active":
            return _deny(403, "restaurant_suspended", "This restaurant is currently unavailable.")
        request.is_platform, request.tenant = is_platform, restaurant
        token = set_current_tenant(restaurant)
        try:
            return self.get_response(request)
        finally:
            reset_current_tenant(token)


    @staticmethod
    def _restaurant_from_path(request):
        """/<slug>/rest... on a platform host: return the restaurant and strip the slug from path_info."""
        from apps.tenants.models import RESERVED_SLUGS, Restaurant

        parts = request.path_info.split("/", 2)  # ["", slug, rest]
        slug = parts[1] if len(parts) > 1 else ""
        if not slug or slug in RESERVED_SLUGS or "." in slug:
            return None
        restaurant = Restaurant.unscoped_objects.filter(slug=slug).first()
        if restaurant is None:
            return None
        request.path_info = "/" + (parts[2] if len(parts) > 2 else "")
        request.tenant_prefix = f"/{slug}"
        return restaurant


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
