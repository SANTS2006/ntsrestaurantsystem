import gzip
from datetime import timedelta

import boto3
import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from moto import mock_aws

from apps.accounts.models import User
from apps.backups import service
from apps.backups.health import system_health
from apps.backups.models import BackupRecord
from apps.backups.storage import R2Storage, StorageError, get_storage
from apps.core.models import AuditLog, IdempotencyKey
from apps.notifications.models import EmailLog
from apps.payments.models import Payment
from apps.tenants.models import Restaurant

from .conftest import client_for

KEY = Fernet.generate_key().decode()
S = "/api/v1/system/"


@pytest.fixture
def local(settings, tmp_path):
    settings.BACKUP_ENCRYPTION_KEY = KEY
    settings.BACKUP_ALLOW_LOCAL = True
    settings.BACKUP_LOCAL_DIR = str(tmp_path / "bk")
    for k in ("R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ACCOUNT_ID", "R2_ENDPOINT_URL"):
        setattr(settings, k, "")
    return tmp_path


@pytest.fixture
def r2(settings):
    settings.BACKUP_ENCRYPTION_KEY = KEY
    settings.BACKUP_ALLOW_LOCAL = False
    settings.R2_BUCKET, settings.R2_ACCESS_KEY_ID, settings.R2_SECRET_ACCESS_KEY = "test-bucket", "test-id", "test-secret"
    settings.R2_ACCOUNT_ID, settings.R2_ENDPOINT_URL = "acct", "https://s3.amazonaws.com"  # moto only intercepts AWS hosts
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="test-bucket")
        yield


def take(**kw):
    return service.run_backup(BackupRecord.objects.create(kind="manual", **kw))


# ---------------- archive contents ----------------
def test_backup_is_encrypted_checksummed_and_verifiable(world, local):
    rec = take()
    assert rec.status == "succeeded" and rec.storage == "local" and rec.size_bytes > 0 and len(rec.sha256) == 64
    assert rec.counts["accounts.user"] == User.objects.count() and rec.counts["tenants.restaurant"] == 2
    stored = get_storage().get(rec.object_key)
    assert b"admin@a.com" not in stored and b"Alpha" not in stored  # ciphertext, not readable data
    assert b"admin@a.com" in gzip.decompress(Fernet(KEY.encode()).decrypt(stored))
    assert service.verify_backup(rec).verify_ok is True and rec.verified_at


def test_sensitive_and_noisy_tables_are_excluded(world, local):
    IdempotencyKey.objects.create(restaurant=world["a"], user=world["admin_a"], operation="x", key="k", request_hash="h")
    EmailLog.objects.create(template="t", to_email="x@y.com")
    rec = take()
    for label in ("core.idempotencykey", "notifications.emaillog", "sessions.session", "backups.backuprecord", "contenttypes.contenttype"):
        assert label not in rec.counts
    assert not any(k.startswith("token_blacklist") for k in rec.counts)


# ---------------- failures are recorded, never raised ----------------
def test_missing_key_or_storage_fails_cleanly(world, local, settings):
    settings.BACKUP_ENCRYPTION_KEY = ""
    r = take()
    assert r.status == "failed" and "BACKUP_ENCRYPTION_KEY" in r.error
    settings.BACKUP_ENCRYPTION_KEY = "not-a-key"
    assert "valid Fernet key" in take().error
    settings.BACKUP_ENCRYPTION_KEY = KEY
    settings.BACKUP_ALLOW_LOCAL = False
    r = take()
    assert r.status == "failed" and "No backup storage" in r.error


# ---------------- Cloudflare R2 (S3 API) ----------------
def test_r2_backup_verify_and_tamper_detection(world, r2):
    assert isinstance(get_storage(), R2Storage)
    rec = take()
    assert rec.status == "succeeded" and rec.storage == "r2", rec.error
    s3 = boto3.client("s3", region_name="us-east-1")
    assert s3.head_object(Bucket="test-bucket", Key=rec.object_key)["ContentLength"] == rec.size_bytes
    assert service.verify_backup(rec).verify_ok is True
    s3.put_object(Bucket="test-bucket", Key=rec.object_key, Body=b"tampered")
    bad = service.verify_backup(rec)
    assert bad.verify_ok is False and "Checksum mismatch" in bad.verify_error


def test_wrong_key_cannot_decrypt(world, local, settings):
    rec = take()
    settings.BACKUP_ENCRYPTION_KEY = Fernet.generate_key().decode()
    r = service.verify_backup(rec)
    assert r.verify_ok is False and "decrypt" in r.verify_error.lower()


def test_storage_mismatch_is_reported(world, local, settings):
    rec = take()
    rec.storage = "r2"
    rec.save()
    assert "stored in r2" in service.verify_backup(rec).verify_error


# ---------------- restore ----------------
def wipe():
    from django.apps import apps

    skip = {"sessions.session", "contenttypes.contenttype", "auth.permission"}
    for model in apps.get_models(include_auto_created=True):  # includes many-to-many through tables
        if model._meta.label_lower not in skip and model._meta.app_label != "backups":
            model._base_manager.all()._raw_delete(model._base_manager.db)


def test_restore_refuses_a_non_empty_database(world, local):
    rec = take()
    with pytest.raises(service.BackupError, match="not empty"):
        service.restore_into_empty_database(rec)


def test_restore_into_empty_database_recovers_everything(world, local):
    rec = take()
    before = dict(rec.counts)
    wipe()
    assert not User.objects.exists() and not Restaurant.unscoped_objects.exists()
    restored = service.restore_into_empty_database(rec)
    assert restored == before
    assert User.objects.filter(email="admin@a.com").exists() and Restaurant.unscoped_objects.filter(slug="alpha").exists()
    assert User.objects.get(email="admin@a.com").check_password("Str0ng-Passw0rd!x")


def test_restore_is_all_or_nothing_on_corruption(world, local):
    rec = take()
    wipe()
    st = get_storage()
    st.put(rec.object_key, b"garbage")
    with pytest.raises(service.BackupError):
        service.restore_into_empty_database(rec)
    assert not User.objects.exists()


def test_restore_command_requires_apply_and_confirmation(world, local, capsys):
    rec = take()
    call_command("restore_backup", rec.pk)
    assert "verified" in capsys.readouterr().out.lower()
    with pytest.raises(CommandError, match="--confirm"):
        call_command("restore_backup", rec.pk, apply=True)
    with pytest.raises(CommandError, match="not empty"):
        call_command("restore_backup", rec.pk, apply=True, confirm=str(rec.pk))
    with pytest.raises(CommandError, match="No such backup"):
        call_command("restore_backup", 99999)


# ---------------- retention ----------------
def test_prune_keeps_newest_and_recent(world, local, settings):
    settings.BACKUP_KEEP_MIN, settings.BACKUP_RETAIN_DAYS = 2, 30
    recs = [take() for _ in range(5)]
    old = timezone.now() - timedelta(days=60)
    for r in recs[:4]:  # the four oldest are beyond retention, the newest is not
        BackupRecord.objects.filter(pk=r.pk).update(created_at=old - timedelta(minutes=r.pk))
    removed = service.prune()
    assert removed == 3  # newest 2 (by created_at) are protected even though one is old
    kept = BackupRecord.objects.filter(pruned_at__isnull=True)
    assert kept.count() == 2
    for r in BackupRecord.objects.filter(pruned_at__isnull=False):
        with pytest.raises(FileNotFoundError):
            get_storage().get(r.object_key)
    assert BackupRecord.objects.count() == 5  # history rows stay


def test_prune_never_removes_recent_backups(world, local, settings):
    settings.BACKUP_KEEP_MIN = 0
    take()
    assert service.prune() == 0


# ---------------- API ----------------
def test_platform_admin_runs_lists_and_verifies_backups(world, local):
    p = client_for(world["platform"])
    r = p.post(S + "backups/")
    assert r.status_code == 201 and r.data["status"] == "succeeded" and r.data["rows"] > 0
    assert "object_key" not in r.data and len(r.data["sha256"]) == 16
    bid = r.data["id"]
    assert p.get(S + "backups/").data[0]["id"] == bid
    v = p.post(S + f"backups/{bid}/verify/")
    assert v.status_code == 200 and v.data["verify_ok"] is True
    assert p.post(S + "backups/99999/verify/").status_code == 404
    acts = set(AuditLog.objects.values_list("action", flat=True))
    assert {"backup.requested", "backup.verified"} <= acts


def test_failed_backup_via_api_is_reported_and_audited(world, local, settings):
    settings.BACKUP_ENCRYPTION_KEY = ""
    r = client_for(world["platform"]).post(S + "backups/")
    assert r.status_code == 201 and r.data["status"] == "failed" and "BACKUP_ENCRYPTION_KEY" in r.data["error"]
    assert AuditLog.objects.filter(action="backup.failed").exists()


def test_only_one_backup_runs_at_a_time(world, local):
    BackupRecord.objects.create(kind="manual", status="running")
    assert client_for(world["platform"]).post(S + "backups/").status_code == 400


def test_backups_and_health_are_platform_admin_on_platform_host_only(world, local):
    for c in (client_for(world["admin_a"]), client_for(world["admin_a"], "alpha"), client_for(world["platform"], "alpha"), client_for(world["cust_a"], "alpha")):
        assert c.get(S + "health/").status_code == 403
        assert c.get(S + "backups/").status_code == 403
        assert c.post(S + "backups/").status_code == 403
        assert c.post(S + "backups/1/verify/").status_code == 403
    from tests.conftest import TenantClient as APIClient
    assert APIClient(HTTP_HOST="platform.test").get(S + "health/").status_code in (401, 403)
    assert BackupRecord.objects.count() == 0


def test_restore_is_never_a_plain_call(world, local):
    """Restoring is possible from the System page, but only through the guarded endpoint (password, phrase, safety snapshot)."""
    p = client_for(world["platform"])
    rec = take()
    assert p.post(S + f"backups/{rec.pk}/restore/", {}, format="json").status_code == 400
    assert p.get(S + f"backups/{rec.pk}/restore/").status_code == 405
    assert p.delete(S + f"backups/{rec.pk}/").status_code in (404, 405)


# ---------------- health ----------------
def by_name(h):
    return {c["name"]: c for c in h["checks"]}


def test_health_reports_each_subsystem_without_secrets(world, local):
    take()
    r = client_for(world["platform"]).get(S + "health/")
    assert r.status_code == 200
    names = by_name(r.data)
    assert {"Database", "Cache", "Task queue", "Real-time channel", "Backup storage", "Backups", "Migrations", "Email delivery", "Payments"} <= set(names)
    assert names["Database"]["status"] == "ok" and names["Backups"]["status"] == "ok" and names["Migrations"]["status"] == "ok"
    blob = str(r.data)
    assert KEY not in blob and "test-secret" not in blob and "postgres" not in blob.lower()


def test_health_flags_stale_failed_and_unverified_backups(world, local):
    assert by_name(system_health())["Backups"]["status"] == "warning"  # none yet
    rec = take()
    BackupRecord.objects.filter(pk=rec.pk).update(finished_at=timezone.now() - timedelta(hours=40))
    assert by_name(system_health())["Backups"]["status"] == "critical"
    BackupRecord.objects.filter(pk=rec.pk).update(finished_at=timezone.now(), verify_ok=False)
    assert by_name(system_health())["Backups"]["status"] == "critical"
    BackupRecord.objects.filter(pk=rec.pk).update(verify_ok=True)
    BackupRecord.objects.create(kind="scheduled", status="failed", error="boom")
    assert by_name(system_health())["Backups"]["status"] == "warning"


def test_health_flags_email_and_payment_trouble(world, local):
    EmailLog.objects.create(template="t", to_email="a@b.com", status="failed")
    h = system_health()
    assert by_name(h)["Email delivery"]["status"] == "warning"
    o = None
    from .test_phase8_management import mk_order
    o, p = mk_order(world, world["a1"], "10.00", paid="10.00")
    Payment.unscoped.filter(pk=p.pk).update(status="mismatch")
    h = system_health()
    assert by_name(h)["Payments"]["status"] == "critical" and h["status"] == "critical"


def test_health_critical_without_encryption_key(world, local, settings):
    settings.BACKUP_ENCRYPTION_KEY = ""
    assert by_name(system_health())["Backups"]["status"] == "critical"


def test_beat_schedule_is_configured(settings, db):
    tasks = {v["task"] for v in settings.CELERY_BEAT_SCHEDULE.values()}
    assert {"apps.payments.tasks.reconcile_payments", "apps.backups.tasks.scheduled_backup", "apps.backups.tasks.prune_backups", "apps.backups.tasks.verify_latest"} <= tasks
    from config.celery import app
    app.loader.import_default_modules()
    for t in tasks:
        assert t in app.tasks, t


def test_scheduled_tasks_run(world, local):
    from apps.backups import tasks
    assert tasks.scheduled_backup() == "succeeded"
    assert tasks.verify_latest() is True
    assert tasks.prune_backups() == 0
    assert BackupRecord.objects.filter(kind="scheduled").count() == 1


# ---------------- disaster recovery into a brand-new database (no BackupRecord rows) ----------------
def test_restore_by_object_key_into_an_empty_database(world, local, capsys):
    rec = take()
    key, before = rec.object_key, dict(rec.counts)
    call_command("restore_backup", list=True)
    assert key in capsys.readouterr().out
    wipe()
    BackupRecord.objects.all().delete()  # a fresh database knows nothing about the archive
    call_command("restore_backup", key=key)
    assert "readable" in capsys.readouterr().out
    with pytest.raises(CommandError, match="RESTORE"):
        call_command("restore_backup", key=key, apply=True)
    call_command("restore_backup", key=key, apply=True, confirm="RESTORE")
    assert User.objects.filter(email="admin@a.com").exists()
    assert sum(before.values()) == sum(1 for _ in service.iter_objects(service.read_archive_by_key(key)))
    with pytest.raises(CommandError):
        call_command("restore_backup")


def test_restore_by_key_detects_tampering_and_wrong_key(world, local, settings):
    rec = take()
    key = rec.object_key
    get_storage().put(key, b"x" * 200)
    with pytest.raises(service.BackupError):
        service.read_archive_by_key(key)
    with pytest.raises(service.BackupError, match="Cannot read"):
        service.read_archive_by_key("backups/does/not/exist.enc")
    with pytest.raises(StorageError):
        get_storage().get("../../etc/passwd")
