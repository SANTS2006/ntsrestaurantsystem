import os

from .base import *  # noqa: F401,F403

DEBUG = False
SINGLE_INSTANCE = os.environ.get("SINGLE_INSTANCE", "").lower() in ("1", "true", "yes")
if not REDIS_URL and not SINGLE_INSTANCE:  # noqa: F405
    raise RuntimeError("REDIS_URL is required in production (rate limiting, cache, Celery, WebSockets). A single-instance deployment may set SINGLE_INSTANCE=true instead.")
if "insecure" in SECRET_KEY.lower() or len(SECRET_KEY) < 40:  # noqa: F405
    raise RuntimeError("DJANGO_SECRET_KEY must be a long random value in production.")
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^healthz$", r"^readyz$"]  # platform health probes arrive without the proxy header
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # TLS terminates at the load balancer
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
if EMAIL_PROVIDER != "brevo" or not BREVO_API_KEY or not BREVO_SENDER_EMAIL:
    raise RuntimeError("Production requires EMAIL_PROVIDER=brevo, BREVO_API_KEY and BREVO_SENDER_EMAIL.")
if PAYMENT_PROVIDER != "monime" or not (MONIME_API_KEY and MONIME_BASE_URL and MONIME_WEBHOOK_SECRET):
    raise RuntimeError("Production requires PAYMENT_PROVIDER=monime with MONIME_API_KEY, MONIME_BASE_URL and MONIME_WEBHOOK_SECRET.")
if not MFA_ENFORCEMENT:  # noqa: F405
    raise RuntimeError("Production requires MFA_ENFORCEMENT=true (two-factor authentication for privileged accounts).")
if UPLOAD_SCANNER not in ("clamav", "builtin") or not UPLOAD_SCAN_FAIL_CLOSED:  # noqa: F405
    raise RuntimeError("Production requires UPLOAD_SCANNER=clamav (or builtin when no ClamAV daemon is available) with UPLOAD_SCAN_FAIL_CLOSED=true.")
if not USE_CLOUDINARY:  # noqa: F405
    raise RuntimeError("Production requires Cloudinary (CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET): the server disk is not permanent.")
STORAGES = {**STORAGES, "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}}  # noqa: F405
