import os

os.environ["DJANGO_SKIP_DOTENV"] = "1"  # tests never read .env: they must not touch real databases, mail, payments or storage

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key-0123456789-0123456789-abcdef")
os.environ["DATABASE_URL"] = "sqlite://:memory:"
os.environ["REDIS_URL"] = ""
os.environ["PLATFORM_DOMAIN"] = "platform.test"
from .base import *  # noqa: E402,F401,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # test speed only
ALLOWED_HOSTS = ["*"]
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_CLASSES": []}  # noqa: F405
INSTALLED_APPS = INSTALLED_APPS + ["tests"]  # noqa: F405  (test-only models)
EMAIL_PROVIDER = "console"
EMAIL_ENQUEUE_ON_COMMIT = False
CELERY_TASK_ALWAYS_EAGER = True
GOOGLE_OAUTH_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
PUBLIC_URL_SCHEME = "http"
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {"anon": "10000/min", "user": "10000/min", "login": "10000/min", "auth": "10000/min", "qr": "10000/min", "catering": "10000/min", "reservations": "10000/min"}  # noqa: F405
TESTING_PAYMENTS = True
PAYMENT_PROVIDER = "simulated"

MFA_ENFORCEMENT = False  # MFA tests switch it on explicitly

USE_CLOUDINARY = False
STORAGES = {**STORAGES, "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}}  # noqa: F405
