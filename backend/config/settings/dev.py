import os

if os.environ.get("DEV_USE_REDIS") != "1":
    os.environ["REDIS_URL"] = ""  # local development runs without Redis (in-memory cache and inline tasks) unless asked
os.environ.setdefault("DJANGO_SECRET_KEY", "dev-only-insecure-key-do-not-use-in-production-0123456789")
from .base import *  # noqa: E402,F401,F403

DEBUG = True
ALLOWED_HOSTS = ["*"]
CORS_ALLOWED_ORIGIN_REGEXES = [r"^http://([a-z0-9-]+\.)?localhost:\d+$"]
PUBLIC_URL_SCHEME = "http"

BACKUP_ALLOW_LOCAL = True  # development only: production must use Cloudflare R2
if not BACKUP_ENCRYPTION_KEY:  # development convenience: derived from the dev secret, never used in production
    import base64
    import hashlib

    BACKUP_ENCRYPTION_KEY = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest()).decode()

MFA_ENFORCEMENT = env_bool("MFA_ENFORCEMENT", False)  # off by default for local development; production always enforces
