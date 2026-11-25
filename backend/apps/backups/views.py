from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts import mfa
from apps.accounts.models import User
from apps.accounts.permissions import IsPlatformAdminOnPlatformHost
from apps.core.models import audit

from . import service
from .health import system_health
from .models import BackupRecord, RestoreRecord
from .tasks import run_backup_task


def backup_json(b):
    return {"id": b.pk, "kind": b.kind, "status": b.status, "storage": b.storage, "size_bytes": b.size_bytes, "sha256": b.sha256[:16], "rows": sum(b.counts.values()),
            "error": b.error, "created_at": b.created_at, "finished_at": b.finished_at, "verified_at": b.verified_at, "verify_ok": b.verify_ok,
            "verify_error": b.verify_error, "pruned": bool(b.pruned_at), "media_files": b.media_files, "media_size_bytes": b.media_size_bytes, "media_note": b.media_note}


class SystemHealthView(APIView):
    permission_classes = [IsPlatformAdminOnPlatformHost]

    def get(self, request):
        return Response(system_health())


class BackupsView(APIView):
    permission_classes = [IsPlatformAdminOnPlatformHost]

    def get(self, request):
        return Response([backup_json(b) for b in BackupRecord.objects.select_related()[:50]])

    def post(self, request):
        with transaction.atomic():
            recent = BackupRecord.objects.select_for_update().filter(status="running", created_at__gte=timezone.now() - timedelta(minutes=30)).exists()
            if recent:
                raise ValidationError({"detail": "A backup is already running."})
            rec = BackupRecord.objects.create(kind="manual", created_by=request.user)
        audit("backup.requested", actor=request.user, obj=rec, request=request)
        run_backup_task.delay(rec.pk)
        rec.refresh_from_db()
        if rec.status == "failed":
            audit("backup.failed", actor=request.user, obj=rec, metadata={"error": rec.error}, request=request)
        return Response(backup_json(rec), status=201)


class BackupVerifyView(APIView):
    permission_classes = [IsPlatformAdminOnPlatformHost]

    def post(self, request, pk):
        rec = BackupRecord.objects.filter(pk=pk).first()
        if rec is None:
            raise NotFound()
        service.verify_backup(rec)
        audit("backup.verified", actor=request.user, obj=rec, metadata={"ok": rec.verify_ok}, request=request)
        return Response(backup_json(rec))


def restore_json(r):
    return {"id": r.pk, "backup_id": r.backup_id, "safety_backup_id": r.safety_backup_id, "status": r.status, "rows": r.rows, "error": r.error, "requested_by": r.requested_by,
            "started_at": r.started_at, "finished_at": r.finished_at}


class RestoresView(APIView):
    permission_classes = [IsPlatformAdminOnPlatformHost]

    def get(self, request):
        return Response([restore_json(r) for r in RestoreRecord.objects.all()[:20]])


class BackupRestoreView(APIView):
    """Replace ALL platform data with a verified backup. Deliberately hard to trigger by accident or by a stolen session:
    platform administrator on the platform host, the current password, a fresh two-step code, and the typed phrase
    RESTORE <id>. A verified safety snapshot of the current data is taken first and every session is revoked afterwards."""

    permission_classes = [IsPlatformAdminOnPlatformHost]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request, pk):
        rec = BackupRecord.objects.filter(pk=pk).first()
        if rec is None:
            raise NotFound()
        if str(request.data.get("confirm", "")).strip() != f"RESTORE {pk}":
            raise ValidationError({"confirm": f"Type RESTORE {pk} to confirm."})
        u = request.user
        if authenticate(request, username=u.email, password=str(request.data.get("password", ""))) is None:
            audit("backup.restore_refused", actor=u, obj=rec, metadata={"reason": "password"}, request=request)
            raise ValidationError({"password": "Your password is not correct."})
        if u.mfa_enabled or mfa.enforced():
            ok, how = mfa.verify(u, str(request.data.get("code", "")))
            if not ok:
                audit("backup.restore_refused", actor=u, obj=rec, metadata={"reason": f"mfa:{how}"}, request=request)
                raise ValidationError({"code": "Enter a current code from your authenticator app." if how != "locked" else "Too many attempts. Try again later."})
        audit("backup.restore_started", actor=u, obj=rec, request=request)
        try:
            job = service.restore_live(rec, u.email)
        except service.RestoreRefused as e:
            raise ValidationError({"detail": str(e)})
        # the live tables were replaced: write the outcome (the actor row may not exist in the restored data, so it is recorded by email)
        audit("backup.restore_" + job.status, actor=User.objects.filter(pk=u.pk).first(), obj=rec, metadata={"restore": job.pk, "rows": job.rows, "by": u.email, "error": job.error}, request=None)
        if job.status != "succeeded":
            return Response({"success": False, "error": {"code": "restore_failed", "message": job.error or "The restore failed. Nothing was changed.", "details": restore_json(job)}}, status=500)
        return Response(restore_json(job))


class CronView(APIView):
    """Scheduled jobs for hosts that have no always-on scheduler (Render free plan): an external timer (cron-job.org, GitHub Actions...)
    calls `POST /api/v1/system/cron/<job>/` with `Authorization: Bearer <CRON_SECRET>`. Disabled (404) when CRON_SECRET is not set."""

    permission_classes = []
    authentication_classes: list = []
    JOBS = ("ping", "backup", "prune", "verify", "reconcile")

    def post(self, request, job):
        import hmac

        secret = getattr(settings, "CRON_SECRET", "")
        if not secret or job not in self.JOBS:
            raise NotFound()
        given = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(given.encode(), secret.encode()):
            audit("cron.refused", metadata={"job": job}, request=request)
            return Response({"success": False, "error": {"code": "unauthorized", "message": "Unauthorized."}}, status=401)
        if job == "ping":
            return Response({"ok": True})
        if job == "backup":
            recent = BackupRecord.objects.filter(kind="scheduled", status="succeeded", created_at__gte=timezone.now() - timedelta(hours=12)).exists()
            if recent:
                return Response({"ok": True, "skipped": "A scheduled backup already ran in the last 12 hours."})
            from .tasks import scheduled_backup

            return Response({"ok": True, "result": scheduled_backup()})
        if job == "prune":
            return Response({"ok": True, "removed": service.prune()})
        if job == "verify":
            from .tasks import verify_latest

            return Response({"ok": True, "verified": verify_latest()})
        from apps.payments.services import reconcile_pending

        return Response({"ok": True, "checked": len(reconcile_pending())})
