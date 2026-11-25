"""Security response headers for the website and the API (Content-Security-Policy, Permissions-Policy, cross-origin isolation)."""
from django.conf import settings

GOOGLE = "https://accounts.google.com"


def csp() -> str:
    parts = {
        "default-src": "'self'",
        "script-src": f"'self' {GOOGLE}/gsi/client",
        "style-src": f"'self' 'unsafe-inline' {GOOGLE}/gsi/style",  # React sets inline style attributes
        "img-src": "'self' data: https://res.cloudinary.com",
        "font-src": "'self'",
        "connect-src": f"'self' wss: {GOOGLE}/gsi/",
        "frame-src": f"{GOOGLE}/gsi/",
        "frame-ancestors": "'none'",
        "base-uri": "'self'",
        "form-action": "'self'",
        "object-src": "'none'",
    }
    if not settings.DEBUG:
        parts["upgrade-insecure-requests"] = ""
    return "; ".join(f"{k} {v}".strip() for k, v in parts.items())


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        resp = self.get_response(request)
        if request.path.startswith("/django-admin"):
            return resp  # the Django admin ships its own inline scripts; it is also restricted to platform staff
        resp.setdefault("Content-Security-Policy", csp())
        resp.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()")
        resp.setdefault("Cross-Origin-Opener-Policy", "same-origin-allow-popups")  # allows the Google sign-in popup
        resp.setdefault("Cross-Origin-Resource-Policy", "same-site")
        if request.path_info.startswith("/api/") and "Cache-Control" not in resp:
            resp["Cache-Control"] = "no-store"  # API answers carry personal and financial data
        return resp
