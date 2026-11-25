"""Base settings. All secrets and environment-specific values come from environment variables."""
import os
from datetime import timedelta
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _load_dotenv():
    """Read backend/.env into the process environment for local runs. Real environment variables always win (so Render and
    CI are unaffected) and tests switch this off (DJANGO_SKIP_DOTENV=1) so they can never reach real services."""
    if os.environ.get("DJANGO_SKIP_DOTENV") == "1":
        return
    path = BASE_DIR / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


_load_dotenv()


def env(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and value in (None, ""):
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def env_bool(name, default=False):
    return str(os.environ.get(name, str(default))).lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY", required=True)
DEBUG = False
PLATFORM_DOMAIN = env("PLATFORM_DOMAIN", "localhost")
# Hostnames that serve the platform (non-tenant) site and platform admin APIs.
PLATFORM_HOSTS = env_list("PLATFORM_HOSTS", PLATFORM_DOMAIN)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", f".{PLATFORM_DOMAIN},{PLATFORM_DOMAIN}")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "drf_spectacular",
    "apps.core",
    "apps.tenants",
    "apps.accounts",
    "apps.catalog",
    "apps.customers",
    "apps.orders",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.security_headers.SecurityHeadersMiddleware",
    "apps.core.middleware.MaintenanceMiddleware",
    "apps.core.middleware.TenantMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

# Neon PostgreSQL via DATABASE_URL (use the pooled connection string).
# The SQLite fallback exists for local smoke runs and the test-suite only.
import sys  # noqa: E402

# Neon: the pooled URL (PgBouncer) serves the app; schema changes must use the DIRECT (non-pooled) URL.
_DB_ENV = "DIRECT_DATABASE_URL" if ("migrate" in sys.argv and os.environ.get("DIRECT_DATABASE_URL")) else "DATABASE_URL"
DATABASES = {
    "default": dj_database_url.config(
        env=_DB_ENV,
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=int(env("DB_CONN_MAX_AGE", "60")),
        conn_health_checks=True,
    )
}
if DATABASES["default"]["ENGINE"].endswith("postgresql"):
    # Neon pooling (pgbouncer, transaction mode) is incompatible with server-side cursors.
    DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True

AUTH_USER_MODEL = "accounts.User"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.PBKDF2PasswordHasher"]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # request-size restriction

# Redis: cache, distributed rate limiting, Celery broker. Local-memory fallback is dev/test only.
REDIS_URL = env("REDIS_URL", "")
if REDIS_URL:
    CACHES = {"default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        "KEY_PREFIX": "nts",
    }}
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_BROKER_URL = REDIS_URL or "memory://"
CELERY_RESULT_BACKEND = REDIS_URL or "cache+memory://"
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework_simplejwt.authentication.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {"anon": "60/min", "user": "240/min", "login": "10/min"},
    "EXCEPTION_HANDLER": "apps.core.api.exception_handler",
    "DEFAULT_RENDERER_CLASSES": ["apps.core.api.EnvelopeJSONRenderer"],
}
SPECTACULAR_SETTINGS = {"TITLE": "NTS Restaurant Platform API", "VERSION": "1.0.0", "SERVE_INCLUDE_SCHEMA": False}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
CORS_ALLOWED_ORIGIN_REGEXES = env_list("CORS_ALLOWED_ORIGIN_REGEXES")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"format": '{"t":"%(asctime)s","lvl":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}

# ---- Phase 2: email, auth flows ---------------------------------------------------------------
INSTALLED_APPS += ["apps.notifications"]
REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] = ["apps.accounts.authentication.VersionedJWTAuthentication"]
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["auth"] = "10/min"

PUBLIC_URL_SCHEME = env("PUBLIC_URL_SCHEME", "https")
EMAIL_PROVIDER = env("EMAIL_PROVIDER", "console")  # "brevo" in production; "console" never logs bodies
BREVO_API_KEY = env("BREVO_API_KEY", "")
BREVO_SENDER_EMAIL = env("BREVO_SENDER_EMAIL", "")
BREVO_SENDER_NAME = env("BREVO_SENDER_NAME", "NTS Restaurant Platform")
EMAIL_ENQUEUE_ON_COMMIT = True
CELERY_TASK_ALWAYS_EAGER = not REDIS_URL  # no broker locally -> run tasks inline

VERIFICATION_CODE_TTL_SECONDS = int(env("VERIFICATION_CODE_TTL_SECONDS", "600"))
VERIFICATION_CODE_MAX_ATTEMPTS = 5
VERIFICATION_RESEND_COOLDOWN_SECONDS = int(env("VERIFICATION_RESEND_COOLDOWN_SECONDS", "60"))
SETUP_TOKEN_TTL_HOURS = int(env("SETUP_TOKEN_TTL_HOURS", "72"))
GOOGLE_OAUTH_CLIENT_ID = env("GOOGLE_OAUTH_CLIENT_ID", "")
TERMS_VERSION = env("TERMS_VERSION", "2026-11-01")
PRIVACY_VERSION = env("PRIVACY_VERSION", "2026-11-01")

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"  # dev only; production uses object storage (Cloudflare R2) in Phase 13
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

# Browsers must be allowed to send the idempotency header cross-origin (preflight would otherwise fail).
from corsheaders.defaults import default_headers  # noqa: E402

CORS_ALLOW_HEADERS = [*default_headers, "idempotency-key"]

# ---- Phase 6: payments ------------------------------------------------------------------------
INSTALLED_APPS = ["daphne", "channels"] + INSTALLED_APPS + ["apps.payments", "apps.cashier", "apps.reports", "apps.qrmenu", "apps.catering", "apps.payroll"]
PAYMENT_PROVIDER = env("PAYMENT_PROVIDER", "simulated")  # "monime" in production
TESTING_PAYMENTS = False  # tests enable the simulated provider without DEBUG
SIMULATED_WEBHOOK_SECRET = env("SIMULATED_WEBHOOK_SECRET", "dev-simulated-webhook-secret")
WEBHOOK_TOLERANCE_SECONDS = 300
MONIME_API_KEY = env("MONIME_API_KEY", "")
MONIME_SPACE_ID = env("MONIME_SPACE_ID", "")
MONIME_WEBHOOK_SECRET = env("MONIME_WEBHOOK_SECRET", "")
# Contract taken from docs.monime.io (API version caph.2025-08-23). The webhook secret is the 32-100 character secret of the webhook you create in the Monime dashboard.
MONIME_BASE_URL = env("MONIME_BASE_URL", "https://api.monime.io/v1")
MONIME_VERSION = env("MONIME_VERSION", "caph.2025-08-23")

# ---- Phase 9: real-time (Django Channels). Redis in production; in-memory layer for single-process dev/tests only.
if REDIS_URL:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [REDIS_URL]}}}
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["qr"] = "20/min"
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["catering"] = "10/hour"
QR_MAX_PENDING_PER_TABLE = 5
WS_AUTH_TIMEOUT_SECONDS = 5

# ---- Phase 13: backups and monitoring -------------------------------------------------------------------------
INSTALLED_APPS += ["apps.backups", "apps.finance", "apps.procurement", "apps.floor"]
R2_ACCOUNT_ID = env("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = env("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = env("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET = env("R2_BUCKET", "")
R2_ENDPOINT_URL = env("R2_ENDPOINT_URL", "")  # defaults to https://<account>.r2.cloudflarestorage.com
BACKUP_ENCRYPTION_KEY = env("BACKUP_ENCRYPTION_KEY", "")  # a Fernet key; backups are refused without it
BACKUP_ALLOW_LOCAL = env_bool("BACKUP_ALLOW_LOCAL", False)  # local-disk backups are a development convenience only
BACKUP_LOCAL_DIR = env("BACKUP_LOCAL_DIR", str(BASE_DIR / "backups"))
BACKUP_RETAIN_DAYS = int(env("BACKUP_RETAIN_DAYS", "30"))
BACKUP_KEEP_MIN = int(env("BACKUP_KEEP_MIN", "7"))  # the newest N successful backups are never pruned
BACKUP_MAX_AGE_HOURS = int(env("BACKUP_MAX_AGE_HOURS", "26"))  # health turns critical when the newest good backup is older

from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {  # run with: celery -A config beat
    "payments-reconcile": {"task": "apps.payments.tasks.reconcile_payments", "schedule": 300.0},
    "backup-daily": {"task": "apps.backups.tasks.scheduled_backup", "schedule": crontab(hour=2, minute=0)},
    "backup-prune": {"task": "apps.backups.tasks.prune_backups", "schedule": crontab(hour=3, minute=0)},
    "backup-verify-weekly": {"task": "apps.backups.tasks.verify_latest", "schedule": crontab(hour=4, minute=0, day_of_week=0)},
}

REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["reservations"] = "20/hour"

# ---- two-factor authentication (TOTP) ------------------------------------------------------------------------------
MFA_ENFORCEMENT = env_bool("MFA_ENFORCEMENT", True)  # privileged accounts must enrol before they can use the API
MFA_REQUIRED_ROLES = tuple(env_list("MFA_REQUIRED_ROLES", "restaurant_admin"))  # platform admins always
MFA_ENCRYPTION_KEY = env("MFA_ENCRYPTION_KEY", "")  # Fernet key; defaults to a key derived from the Django secret
MFA_ISSUER = env("MFA_ISSUER", "")

# ---- upload scanning ----------------------------------------------------------------------------------------------
UPLOAD_SCANNER = env("UPLOAD_SCANNER", "off")  # "clamav" in production (a clamd daemon must be reachable)
CLAMAV_HOST = env("CLAMAV_HOST", "127.0.0.1")
CLAMAV_PORT = int(env("CLAMAV_PORT", "3310"))
CLAMAV_SOCKET = env("CLAMAV_SOCKET", "")
UPLOAD_SCAN_FAIL_CLOSED = env_bool("UPLOAD_SCAN_FAIL_CLOSED", True)  # refuse uploads when the scanner cannot be reached
BACKUP_MEDIA_MAX_MB = int(env("BACKUP_MEDIA_MAX_MB", "500"))  # larger media libraries need bucket versioning instead

# ---- file storage: Cloudinary for uploads when configured, static files through WhiteNoise ---------------------------
CLOUDINARY_CLOUD_NAME = env("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = env("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = env("CLOUDINARY_API_SECRET", "")
USE_CLOUDINARY = bool(CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET)
STORAGES = {
    "default": {"BACKEND": "apps.core.cloudinary_storage.CloudinaryStorage" if USE_CLOUDINARY else "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# ---- the website (React build) is served by this backend ------------------------------------------------------------
SPA_DIR = BASE_DIR / "spa"              # hashed assets, logos, favicon (filled by render-build.sh from frontend/dist)
SPA_INDEX = BASE_DIR / "spa_index.html"  # index.html lives outside WhiteNoise's root: spa.py serves it with runtime meta tags
if SPA_DIR.is_dir():
    WHITENOISE_ROOT = SPA_DIR
    WHITENOISE_MAX_AGE = 3600
    WHITENOISE_IMMUTABLE_FILE_TEST = lambda path, url: url.startswith("/assets/")  # noqa: E731  (Vite names these files by content hash)

# Render sets RENDER_EXTERNAL_HOSTNAME (the *.onrender.com address): it always serves the platform site.
_RENDER_HOST = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
if _RENDER_HOST:
    PLATFORM_HOSTS = list(dict.fromkeys([*PLATFORM_HOSTS, _RENDER_HOST]))
    ALLOWED_HOSTS = list(dict.fromkeys([*ALLOWED_HOSTS, _RENDER_HOST]))
    CSRF_TRUSTED_ORIGINS = list(dict.fromkeys([*CSRF_TRUSTED_ORIGINS, f"https://{_RENDER_HOST}"]))
