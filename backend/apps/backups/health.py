"""System health for platform administrators. Never returns secrets, hostnames or connection strings."""
import platform
import time
from datetime import timedelta

import django
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from apps.notifications.models import EmailLog
from apps.payments.models import Payment

from .models import BackupRecord
from .storage import StorageError, get_storage

ORDER = {"ok": 0, "warning": 1, "critical": 2}


def _check(name, status, detail):
    return {"name": name, "status": status, "detail": detail}


def _database():
    t = time.perf_counter()
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:  # noqa: BLE001
        return _check("Database", "critical", "Cannot run a query.")
    ms = round((time.perf_counter() - t) * 1000)
    return _check("Database", "warning" if ms > 500 else "ok", f"{connection.vendor}, answered in {ms} ms")


def _cache():
    try:
        cache.set("health", "1", 5)
        return _check("Cache", "ok" if cache.get("health") == "1" else "critical", "Reads and writes work." if cache.get("health") == "1" else "Write was not readable.")
    except Exception:  # noqa: BLE001
        return _check("Cache", "critical", "Cannot reach the cache.")


def _broker():
    if not getattr(settings, "REDIS_URL", ""):
        return _check("Task queue", "warning", "No Redis configured: tasks run inline and scheduled jobs (backups, payment reconciliation) will not run.")
    try:
        from config.celery import app

        with app.connection_for_read() as c:
            c.ensure_connection(max_retries=1)
        return _check("Task queue", "ok", "Broker reachable. Confirm a worker and beat are running.")
    except Exception:  # noqa: BLE001
        return _check("Task queue", "critical", "Cannot reach the task broker.")


def _channels():
    backend = settings.CHANNEL_LAYERS["default"]["BACKEND"]
    if "InMemory" in backend:
        return _check("Real-time channel", "warning", "In-memory layer: live updates work in one process only.")
    return _check("Real-time channel", "ok", "Redis channel layer configured.")


def _storage():
    try:
        st = get_storage()
        st.check()
    except StorageError as e:
        return _check("Backup storage", "critical", str(e))
    except Exception:  # noqa: BLE001
        return _check("Backup storage", "critical", "Configured storage is not reachable.")
    if st.name == "local":
        return _check("Backup storage", "warning", "Local disk (development only). Use Cloudflare R2 in production.")
    return _check("Backup storage", "ok", "Cloudflare R2 bucket reachable.")


def _backups():
    key_ok = bool(settings.BACKUP_ENCRYPTION_KEY)
    good = BackupRecord.objects.filter(status="succeeded", pruned_at__isnull=True).first()
    last = BackupRecord.objects.first()
    if not key_ok:
        return _check("Backups", "critical", "BACKUP_ENCRYPTION_KEY is not set: backups cannot run.")
    if good is None:
        return _check("Backups", "warning" if last is None else "critical", "No backup has been taken yet." if last is None else "No successful backup exists.")
    age = timezone.now() - good.finished_at
    hours = round(age.total_seconds() / 3600, 1)
    if age > timedelta(hours=settings.BACKUP_MAX_AGE_HOURS):
        return _check("Backups", "critical", f"The newest good backup is {hours} hours old (limit {settings.BACKUP_MAX_AGE_HOURS}).")
    if last.status == "failed":
        return _check("Backups", "warning", f"The most recent attempt failed; the newest good backup is {hours} hours old.")
    if good.verify_ok is False:
        return _check("Backups", "critical", "The newest backup failed verification.")
    return _check("Backups", "ok", f"Newest good backup is {hours} hours old" + ("" if good.verify_ok else " (not yet verified)") + ".")


def _scanner():
    from apps.core import scanning

    if getattr(settings, "UPLOAD_SCANNER", "off") != "clamav":
        return _check("Upload scanning", "warning", "Only the built-in checks run (no antivirus). Production requires ClamAV.")
    if scanning.ping():
        return _check("Upload scanning", "ok", "ClamAV answers.")
    return _check("Upload scanning", "critical" if getattr(settings, "UPLOAD_SCAN_FAIL_CLOSED", True) else "warning", "ClamAV is not reachable: uploads are refused." if getattr(settings, "UPLOAD_SCAN_FAIL_CLOSED", True) else "ClamAV is not reachable.")


def _mfa():
    from apps.accounts.models import User

    if not getattr(settings, "MFA_ENFORCEMENT", False):
        return _check("Two-factor authentication", "warning", "Not enforced for privileged accounts.")
    pending = User.objects.filter(is_active=True, is_platform_admin=True, mfa_enabled=False).count()
    return _check("Two-factor authentication", "warning" if pending else "ok", f"{pending} platform administrator(s) have not enrolled yet." if pending else "Enforced; every platform administrator has enrolled.")


def _migrations():
    try:
        pending = MigrationExecutor(connection).migration_plan(MigrationExecutor(connection).loader.graph.leaf_nodes())
    except Exception:  # noqa: BLE001
        return _check("Migrations", "warning", "Could not check.")
    return _check("Migrations", "critical" if pending else "ok", f"{len(pending)} unapplied migration(s)." if pending else "All applied.")


def _email():
    now = timezone.now()
    failed = EmailLog.objects.filter(status="failed", created_at__gte=now - timedelta(hours=24)).count()
    stuck = EmailLog.objects.filter(status__in=["queued", "retrying"], created_at__lte=now - timedelta(minutes=15)).count()
    status = "critical" if failed >= 10 or stuck >= 10 else "warning" if failed or stuck else "ok"
    return _check("Email delivery", status, f"{failed} failed in the last 24 h, {stuck} waiting more than 15 min. Provider: {settings.EMAIL_PROVIDER}.")


def _payments():
    now = timezone.now()
    stuck = Payment.unscoped.filter(status="pending", created_at__lte=now - timedelta(hours=1)).count()
    mismatch = Payment.unscoped.filter(status="mismatch").count()
    status = "critical" if mismatch else "warning" if stuck else "ok"
    return _check("Payments", status, f"{stuck} pending for over an hour, {mismatch} amount mismatch(es) needing investigation.")


def system_health():
    checks = [_database(), _cache(), _broker(), _channels(), _storage(), _backups(), _scanner(), _mfa(), _migrations(), _email(), _payments()]
    overall = max((c["status"] for c in checks), key=ORDER.get)
    return {
        "status": overall, "checked_at": timezone.now().isoformat(), "checks": checks,
        "runtime": {"python": platform.python_version(), "django": django.get_version(), "debug": settings.DEBUG, "payment_provider": settings.PAYMENT_PROVIDER,
                    "email_provider": settings.EMAIL_PROVIDER},
        "config": {"backup_retain_days": settings.BACKUP_RETAIN_DAYS, "backup_keep_min": settings.BACKUP_KEEP_MIN, "backup_max_age_hours": settings.BACKUP_MAX_AGE_HOURS},
    }
