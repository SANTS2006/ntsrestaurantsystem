"""Production readiness check: `python manage.py preflight` (run it in the production environment, after deploy and before go-live).

It inspects the ACTIVE configuration and live dependencies and prints PASS / WARN / FAIL for each item.
Exit code 1 if anything fails. It never prints secret values.
"""
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    help = "Check that the active configuration and dependencies are ready for production."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true", help="Treat warnings as failures.")

    def handle(self, *args, **opts):
        rows = []

        def add(level, name, detail=""):
            rows.append((level, name, detail))

        s = settings
        add("PASS" if not s.DEBUG else "FAIL", "DEBUG is off")
        add("PASS" if len(s.SECRET_KEY) >= 50 and "insecure" not in s.SECRET_KEY.lower() else "FAIL", "Secret key is long and random")
        add("PASS" if s.ALLOWED_HOSTS and "*" not in s.ALLOWED_HOSTS else "FAIL", "ALLOWED_HOSTS is explicit", "never '*' in production")
        dom = s.PLATFORM_DOMAIN
        add("PASS" if dom and "localhost" not in dom and "." in dom else "FAIL", "PLATFORM_DOMAIN is a real domain", dom or "unset")
        cors = list(getattr(s, "CORS_ALLOWED_ORIGINS", []) or []) + list(getattr(s, "CORS_ALLOWED_ORIGIN_REGEXES", []) or [])
        add("PASS" if cors and not any("localhost" in c for c in cors) and not getattr(s, "CORS_ALLOW_ALL_ORIGINS", False) else "FAIL", "CORS allows only your own origins")
        add("PASS" if getattr(s, "SECURE_SSL_REDIRECT", False) and s.SESSION_COOKIE_SECURE and s.CSRF_COOKIE_SECURE else "FAIL", "HTTPS redirect and secure cookies")
        add("PASS" if getattr(s, "SECURE_HSTS_SECONDS", 0) >= 31536000 else "WARN", "HSTS is enabled (one year)")
        add("PASS" if getattr(s, "SECURE_PROXY_SSL_HEADER", None) else "WARN", "Proxy TLS header is trusted", "needed behind a load balancer")

        add("PASS" if connection.vendor == "postgresql" else "FAIL", "Database is PostgreSQL", connection.vendor)
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
            add("PASS", "Database answers queries")
        except Exception as e:  # noqa: BLE001
            add("FAIL", "Database answers queries", type(e).__name__)
        try:
            pending = MigrationExecutor(connection).migration_plan(MigrationExecutor(connection).loader.graph.leaf_nodes())
            add("PASS" if not pending else "FAIL", "All migrations applied", f"{len(pending)} pending" if pending else "")
        except Exception:  # noqa: BLE001
            add("WARN", "All migrations applied", "could not check")

        redis_url = getattr(s, "REDIS_URL", "")
        single = bool(os.environ.get("SINGLE_INSTANCE"))
        add("PASS" if redis_url else ("WARN" if single else "FAIL"), "Redis is configured (cache, rate limits, Celery, WebSockets)", "single-instance mode: in-memory cache and inline tasks, one process only" if not redis_url and single else "")
        if redis_url:
            try:
                import redis

                redis.from_url(redis_url, socket_connect_timeout=3).ping()
                add("PASS", "Redis answers PING")
            except Exception as e:  # noqa: BLE001
                add("FAIL", "Redis answers PING", type(e).__name__)
        add("PASS" if "Redis" in s.CHANNEL_LAYERS["default"]["BACKEND"] else ("WARN" if single else "FAIL"), "WebSocket channel layer uses Redis")
        add("PASS" if not s.CELERY_TASK_ALWAYS_EAGER else ("WARN" if single else "FAIL"), "Celery tasks run on a worker (not inline)")
        add("PASS" if (s.CELERY_BEAT_SCHEDULE and not single) or getattr(s, "CRON_SECRET", "") else "WARN", "Scheduled jobs are triggered", "Celery beat, or an external scheduler calling /api/v1/system/cron/<job>/ with CRON_SECRET")

        add("PASS" if s.EMAIL_PROVIDER == "brevo" and s.BREVO_API_KEY and s.BREVO_SENDER_EMAIL else "FAIL", "Email provider is Brevo and configured")
        add("PASS" if s.PAYMENT_PROVIDER == "monime" and s.MONIME_API_KEY and s.MONIME_SPACE_ID else "FAIL", "Payments use Monime with an API key and Space ID")
        add("PASS" if 32 <= len(s.MONIME_WEBHOOK_SECRET) <= 100 else "FAIL", "Monime webhook secret is 32-100 characters", "create the webhook in the Monime dashboard and paste its secret; without it payments cannot be confirmed by webhook")
        add("PASS" if s.GOOGLE_OAUTH_CLIENT_ID else "WARN", "Google sign-in client id set")

        from apps.backups.service import _fernet, BackupError
        from apps.backups.storage import get_storage, r2_configured

        add("PASS" if r2_configured() else "FAIL", "Cloudflare R2 backup storage configured")
        try:
            _fernet()
            add("PASS", "Backup encryption key is valid")
        except BackupError as e:
            add("FAIL", "Backup encryption key is valid", str(e))
        try:
            st = get_storage()
            st.check()
            add("PASS" if st.name == "r2" else "FAIL", "Backup bucket is reachable", st.name)
        except Exception as e:  # noqa: BLE001
            add("FAIL", "Backup bucket is reachable", type(e).__name__)
        from apps.backups.health import _backups

        b = _backups()
        add({"ok": "PASS", "warning": "WARN", "critical": "FAIL"}[b["status"]], "A recent verified backup exists", b["detail"])

        add("PASS" if getattr(s, "MFA_ENFORCEMENT", False) else "FAIL", "Two-factor authentication is enforced for privileged accounts")
        from apps.core import scanning

        if getattr(s, "UPLOAD_SCANNER", "off") == "clamav":
            add("PASS" if scanning.ping() else "FAIL", "ClamAV (upload scanning) answers PING")
        elif getattr(s, "UPLOAD_SCANNER", "off") == "builtin":
            add("WARN", "Upload scanning uses ClamAV", "builtin checks and image re-encoding only: no antivirus engine")
        else:
            add("FAIL", "Upload scanning uses ClamAV", "UPLOAD_SCANNER is off")
        add("PASS" if getattr(s, "UPLOAD_SCAN_FAIL_CLOSED", True) else "FAIL", "Uploads are refused when the scanner is down")

        for lvl, name, detail in rows:
            style = {"PASS": self.style.SUCCESS, "WARN": self.style.WARNING, "FAIL": self.style.ERROR}[lvl]
            self.stdout.write(f"{style(lvl):<14} {name}" + (f"  ({detail})" if detail else ""))
        fails = sum(1 for r in rows if r[0] == "FAIL")
        warns = sum(1 for r in rows if r[0] == "WARN")
        self.stdout.write(f"\n{len(rows) - fails - warns} passed, {warns} warning(s), {fails} failed")
        if fails or (opts["strict"] and warns):
            raise CommandError("Preflight failed.")
