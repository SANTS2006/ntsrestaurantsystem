import time

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.accounts import mfa
from apps.accounts.models import Role, User
from apps.backups import service
from apps.backups.models import BackupRecord, RestoreRecord
from apps.backups.storage import get_storage
from apps.core.models import AuditLog
from apps.tenants.models import Restaurant

from .conftest import PW, client_for
from .test_phase13_backups import local  # noqa: F401  (fixture)

S = "/api/v1/system/"


def take():
    return service.run_backup(BackupRecord.objects.create(kind="manual"))


def restore(c, rec, **over):
    body = {"confirm": f"RESTORE {rec.pk}", "password": PW, **over}
    return c.post(S + f"backups/{rec.pk}/restore/", body, format="json")


@pytest.fixture(autouse=True)
def clean(db):
    cache.clear()


def test_restore_replaces_everything_and_keeps_a_safety_snapshot(world, local):  # noqa: F811
    rec = take()
    before = {"users": User.objects.count(), "restaurants": Restaurant.unscoped_objects.count()}
    User.objects.create_user("later@x.com", PW, email_verified=True)  # created after the backup
    Restaurant.objects.create(name="Gamma", slug="gamma")
    token_before = User.objects.get(email="admin@a.com").token_version
    r = restore(client_for(world["platform"]), rec)
    assert r.status_code == 200, r.content
    d = r.json()["data"]
    assert d["status"] == "succeeded" and d["rows"] == sum(rec.counts.values()) and d["safety_backup_id"] and d["requested_by"] == "root@x.com"
    assert User.objects.count() == before["users"] and not User.objects.filter(email="later@x.com").exists()
    assert not Restaurant.unscoped_objects.filter(slug="gamma").exists() and Restaurant.unscoped_objects.count() == before["restaurants"]
    assert User.objects.get(email="admin@a.com").token_version == token_before + 1  # every session was revoked
    assert not service.maintenance_on()
    safety = BackupRecord.objects.get(pk=d["safety_backup_id"])
    assert safety.status == "succeeded" and safety.verify_ok is True
    assert safety.counts["accounts.user"] == before["users"] + 1  # the snapshot contains what the restore removed
    # the audit log is part of the restored data: entries made after the backup (including "restore started") live on in the safety snapshot
    assert "backup.restore_succeeded" in set(AuditLog.objects.values_list("action", flat=True))
    assert BackupRecord.objects.filter(pk=rec.pk).exists() and RestoreRecord.objects.get().status == "succeeded"  # records outlive the restore


def test_restoring_the_safety_snapshot_undoes_a_restore(world, local):  # noqa: F811
    rec = take()
    Restaurant.objects.create(name="Gamma", slug="gamma")
    d = restore(client_for(world["platform"]), rec).json()["data"]
    assert not Restaurant.unscoped_objects.filter(slug="gamma").exists()
    snap = BackupRecord.objects.get(pk=d["safety_backup_id"])
    assert restore(client_for(User.objects.get(email="root@x.com")), snap).status_code == 200
    assert Restaurant.unscoped_objects.filter(slug="gamma").exists()


def test_restore_demands_password_confirmation_phrase_and_the_second_factor(world, local):  # noqa: F811
    rec = take()
    c = client_for(world["platform"])
    n = User.objects.count()
    assert c.post(S + f"backups/{rec.pk}/restore/", {"password": PW}, format="json").status_code == 400
    assert c.post(S + f"backups/{rec.pk}/restore/", {"password": PW, "confirm": "restore"}, format="json").status_code == 400
    assert restore(c, rec, password="wrong").status_code == 400
    assert restore(c, rec, confirm=f"RESTORE {rec.pk + 1}").status_code == 400
    # an enrolled administrator must also present a current code
    root = User.objects.get(email="root@x.com")
    secret = mfa.new_secret()
    from apps.accounts.models import MFADevice
    MFADevice.objects.create(user=root, secret_enc=mfa._fernet().encrypt(secret.encode()).decode(), confirmed_at=timezone.now())
    User.objects.filter(pk=root.pk).update(mfa_enabled=True)
    c = client_for(User.objects.get(pk=root.pk))  # a fresh client sees the enrolled state
    assert restore(c, rec).status_code == 400
    assert restore(c, rec, code="000000").status_code == 400
    assert User.objects.count() == n and RestoreRecord.objects.count() == 0
    assert "backup.restore_refused" in set(AuditLog.objects.values_list("action", flat=True))  # refusals are audited (before a restore replaces the log)
    ok = restore(c, rec, code=mfa.totp_at(secret, time.time() + 30))
    assert ok.status_code == 200


def test_only_platform_admins_on_the_platform_host_can_restore(world, local):  # noqa: F811
    rec = take()
    for c in (client_for(world["admin_a"]), client_for(world["admin_a"], "alpha"), client_for(world["platform"], "alpha"), client_for(world["cust_a"], "alpha")):
        assert restore(c, rec).status_code == 403
    assert client_for(world["admin_a"], "alpha").get(S + "restores/").status_code == 403
    assert RestoreRecord.objects.count() == 0


def test_a_damaged_backup_is_refused_before_anything_changes(world, local):  # noqa: F811
    rec = take()
    User.objects.create_user("later@x.com", PW, email_verified=True)
    get_storage().put(rec.object_key, b"tampered")
    r = restore(client_for(world["platform"]), rec)
    assert r.status_code == 500 and RestoreRecord.objects.get().status == "failed"
    assert User.objects.filter(email="later@x.com").exists() and not service.maintenance_on()


def test_a_failure_while_loading_rolls_everything_back(world, local, monkeypatch):  # noqa: F811
    rec = take()
    User.objects.create_user("later@x.com", PW, email_verified=True)
    real, calls = service.iter_objects, {"n": 0}

    def flaky(data):
        calls["n"] += 1
        for i, obj in enumerate(real(data)):
            if calls["n"] >= 3 and i == 25:  # calls 1-2 are the two verifications; call 3 is the real load
                raise RuntimeError("disk full")
            yield obj

    monkeypatch.setattr(service, "iter_objects", flaky)
    r = restore(client_for(world["platform"]), rec)
    assert r.status_code == 500 and "disk full" in r.json()["error"]["message"]
    assert User.objects.filter(email="later@x.com").exists() and User.objects.filter(email="admin@a.com").exists()  # nothing was lost
    assert Restaurant.unscoped_objects.filter(slug="alpha").exists() and not service.maintenance_on()
    assert RestoreRecord.objects.get().status == "failed"


def test_pruned_or_failed_backups_cannot_be_restored(world, local):  # noqa: F811
    rec = take()
    BackupRecord.objects.filter(pk=rec.pk).update(pruned_at=timezone.now())
    assert restore(client_for(world["platform"]), BackupRecord.objects.get(pk=rec.pk)).status_code == 400
    failed = BackupRecord.objects.create(kind="manual", status="failed")
    assert restore(client_for(world["platform"]), failed).status_code == 400
    assert restore(client_for(world["platform"]), type("R", (), {"pk": 99999})()).status_code == 404


def test_only_one_restore_runs_at_a_time(world, local):  # noqa: F811
    rec = take()
    RestoreRecord.objects.create(backup=rec, requested_by="x@y.z")
    r = restore(client_for(world["platform"]), rec)
    assert r.status_code == 400 and "already running" in str(r.json())


def test_maintenance_mode_blocks_requests_except_health_checks(world, local):  # noqa: F811
    cache.set(service.MAINTENANCE_KEY, 1, 60)
    c = client_for(world["admin_a"], "alpha")
    r = c.get("/api/v1/payroll/employees/")
    assert r.status_code == 503 and r["Retry-After"] == "120" and r.json()["error"]["code"] == "maintenance"
    from tests.conftest import APIClient as _C
    assert _C(HTTP_HOST="platform.test").get("/healthz").status_code == 200
    cache.delete(service.MAINTENANCE_KEY)
    assert c.get("/api/v1/payroll/employees/").status_code == 200


def test_restore_history_lists_outcomes(world, local):  # noqa: F811
    rec = take()
    c = client_for(world["platform"])
    restore(c, rec)
    rows = client_for(User.objects.get(email="root@x.com")).get(S + "restores/").json()["data"]
    assert rows[0]["status"] == "succeeded" and rows[0]["backup_id"] == rec.pk
    _ = Role


def test_command_line_restore_still_refuses_a_non_empty_database(world, local):  # noqa: F811
    rec = take()
    with pytest.raises(service.BackupError, match="not empty"):
        service.restore_into_empty_database(rec)
