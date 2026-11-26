"""robots.txt and sitemap.xml, per host. Tenant hosts list only that restaurant's own pages."""
from django.conf import settings
from django.http import HttpResponse
from django.utils.html import escape

from .models import Product

PLATFORM_PATHS = ["/", "/features", "/pricing", "/about", "/faq", "/contact"] + [
    f"/legal/{s}" for s in ("privacy-policy", "terms-of-service", "payment-terms", "refund-and-cancellation-policy",
                            "cookie-policy", "security-policy", "acceptable-use-policy")]
TENANT_PATHS = ["/", "/menu", "/services", "/catering", "/gallery", "/about", "/contact", "/faq",
                "/policies/privacy-policy", "/policies/terms-of-use", "/policies/payment-policy",
                "/policies/refund-and-cancellation-policy"]


def _base(request):
    if request.tenant is not None:
        return request.tenant.public_url
    return f"{settings.PUBLIC_URL_SCHEME}://{settings.PLATFORM_DOMAIN}"


def robots_txt(request):
    base = _base(request)
    private = ["manage", "account", "cart", "checkout", "login", "register", "setup-password", "forgot-password", "verify-email", "receipts", "quotation", "reservation/", "t/", "payment-complete"]
    disallow = ["/admin", "/login", "/forgot-password", *[f"/*/{p}" for p in private]] if request.tenant is None else ["/manage", "/account", "/login", "/setup-password", "/quotation", "/t/"]
    body = "User-agent: *\n" + "".join(f"Disallow: {p}\n" for p in disallow) + f"Sitemap: {base}/sitemap.xml\n"
    return HttpResponse(body, content_type="text/plain")


def sitemap_xml(request):
    base = _base(request)
    paths = list(PLATFORM_PATHS if request.tenant is None else TENANT_PATHS)
    if request.tenant is not None:
        slugs = (Product.unscoped.filter(restaurant=request.tenant, is_archived=False, is_available=True,
                                         category__is_active=True).values_list("slug", flat=True))
        paths += [f"/menu/{s}" for s in slugs]
    locations = [base + p for p in paths]
    if request.tenant is None:
        from apps.tenants.models import Restaurant

        for r in Restaurant.unscoped_objects.filter(status="active").order_by("slug")[:2000]:
            locations += [r.public_url, f"{r.public_url}/menu", f"{r.public_url}/reserve", f"{r.public_url}/contact"]
    urls = "".join(f"<url><loc>{escape(u)}</loc></url>" for u in locations)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return HttpResponse(xml, content_type="application/xml")
