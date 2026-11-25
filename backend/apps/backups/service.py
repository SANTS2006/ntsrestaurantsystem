"""Encrypted logical backups of the whole platform database.

An archive is gzip-compressed JSON Lines (Django serializers), then encrypted with Fernet (BACKUP_ENCRYPTION_KEY).
The stored object's SHA-256 and per-model row counts are recorded so a backup can be verified without restoring it.
Restoring is deliberately NOT available through the API: it is a management command that loads only into an empty database.

Limits (stated plainly): the archive is built in memory, so this suits small and medium databases; for large production
data rely on the database provider's point-in-time recovery (Neon) and treat this as the application-level safety net.
Uploaded media files are not included (they are stored separately).
"""
import gzip
import hashlib
import io
import secrets
import tarfile
from pathlib import Path
from collections import Counter
from datetime import timedelta

from cryptography.fernet import Fernet, InvalidToken
from django.apps import apps
from django.conf import settings
from django.core import serializers
from django.db import connection, transaction
from django.utils import timezone

from .models import BackupRecord, RestoreRecord
from .storage import StorageError, get_storage

EXCLUDED = {"sessions.session", "contenttypes.contenttype", "auth.permission", "admin.logentry", "core.idempotencykey",
            "backups.backuprecord", "backups.restorerecord", "notifications.emaillog"}
EXCLUDED_APPS = {"token_blacklist", "tests"}
FORMAT = 1


class BackupError(Exception):
    pass


def _fernet():
    key = settings.BACKUP_ENCRYPTION_KEY
    if not key:
        raise BackupError("BACKUP_ENCRYPTION_KEY is not set.")
    try:
        return Fernet(key.encode())
    except Exception as e:  # noqa: BLE001
        raise BackupError("BACKUP_ENCRYPTION_KEY is not a valid Fernet key.") from e


def backed_up_models():
    return [m for m in apps.get_models() if m._meta.label_lower not in EXCLUDED and m._meta.app_label not in EXCLUDED_APPS and not m._meta.proxy]


def build_archive() -> tuple[bytes, dict]:
    """Return (gzip bytes, row counts), read inside one transaction."""
    counts: Counter = Counter()
    raw = io.BytesIO()
    with transaction.atomic(), gzip.GzipFile(fileobj=raw, mode="wb") as gz:
        gz.write(f'{{"format": {FORMAT}, "created_at": "{timezone.now().isoformat()}", "vendor": "{connection.vendor}"}}\n'.encode())
        for model in backed_up_models():
            qs = model._base_manager.order_by("pk")
            for line in serializers.serialize("jsonl", qs.iterator(chunk_size=500)).splitlines():
                gz.write(line.encode() + b"\n")
                counts[model._meta.label_lower] += 1
    return raw.getvalue(), dict(counts)


def build_media_archive():
    """tar.gz of every uploaded file under MEDIA_ROOT. Returns (bytes, file_count) or (None, 0) when there is nothing to save.
    Built in memory: refused above BACKUP_MEDIA_MAX_MB so a huge media library cannot exhaust the server (use bucket versioning then)."""
    root = Path(settings.MEDIA_ROOT)
    if not root.is_dir():
        return None, 0
    files = [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
    if not files:
        return None, 0
    total = sum(p.stat().st_size for p in files)
    if total > settings.BACKUP_MEDIA_MAX_MB * 1024 * 1024:
        raise BackupError(f"Media is {total // (1024 * 1024)} MB, above the {settings.BACKUP_MEDIA_MAX_MB} MB in-app limit.")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in sorted(files):
            tar.add(p, arcname=p.relative_to(root).as_posix(), recursive=False)
    return buf.getvalue(), len(files)


def _key(kind="backups", ext="bin.enc"):
    now = timezone.now()
    label = "backup" if kind == "backups" else "media"
    return f"{kind}/{now:%Y/%m}/nts-{label}-{now:%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}.{ext}"


def run_backup(record: BackupRecord) -> BackupRecord:
    """Fill in an existing RUNNING record. Never raises: failures are stored on the record (and surface in health)."""
    try:
        storage = get_storage()
        plain, counts = build_archive()
        blob = _fernet().encrypt(plain)
        key = _key()
        storage.put(key, blob)
        try:  # media is a second, independent archive: a media problem is reported but never discards the database backup
            media, n = (None, 0) if settings.USE_CLOUDINARY else build_media_archive()
            if settings.USE_CLOUDINARY:
                record.media_note = "Uploads are stored in Cloudinary, which keeps its own copies."
            elif media is not None:
                mblob = _fernet().encrypt(media)
                mkey = _key("media", "tar.gz.enc")
                storage.put(mkey, mblob)
                record.media_object_key, record.media_sha256, record.media_size_bytes, record.media_files = mkey, hashlib.sha256(mblob).hexdigest(), len(mblob), n
            else:
                record.media_note = "No uploaded files to back up."
        except Exception as e:  # noqa: BLE001
            record.media_note = f"Media not backed up: {type(e).__name__}: {e}"[:200]
        record.storage, record.object_key, record.size_bytes = storage.name, key, len(blob)
        record.sha256, record.counts, record.status, record.error = hashlib.sha256(blob).hexdigest(), counts, BackupRecord.Status.SUCCEEDED, ""
    except Exception as e:  # noqa: BLE001
        record.status, record.error = BackupRecord.Status.FAILED, f"{type(e).__name__}: {e}"[:300]
    record.finished_at = timezone.now()
    record.save()
    return record


def _storage_for(record):
    if not record.object_key or record.pruned_at:
        raise BackupError("This backup is no longer in storage.")
    st = get_storage()
    if st.name != record.storage:
        raise BackupError(f"This backup is stored in {record.storage} but {st.name} is configured.")
    return st


def read_archive(record: BackupRecord) -> bytes:
    """Download, check the checksum, decrypt and decompress. Raises BackupError with a clear reason on any problem."""
    return _open(_storage_for(record).get(record.object_key), record.sha256)


def read_archive_by_key(key: str) -> bytes:
    """For disaster recovery into an empty database that has no BackupRecord rows. Fernet encryption is authenticated,
    so tampering is still detected even without the recorded checksum."""
    try:
        blob = get_storage().get(key)
    except Exception as e:  # noqa: BLE001
        raise BackupError(f"Cannot read that object from storage: {type(e).__name__}") from e
    return _open(blob, None)


def _open(blob: bytes, sha256):
    if sha256 and hashlib.sha256(blob).hexdigest() != sha256:
        raise BackupError("Checksum mismatch: the stored archive was altered or corrupted.")
    try:
        plain = _fernet().decrypt(blob)
    except InvalidToken as e:
        raise BackupError("Cannot decrypt: wrong key or corrupted archive.") from e
    return gzip.decompress(plain)


def read_media(record: BackupRecord) -> bytes:
    blob = _storage_for(record).get(record.media_object_key)
    if hashlib.sha256(blob).hexdigest() != record.media_sha256:
        raise BackupError("Media checksum mismatch: the stored archive was altered or corrupted.")
    try:
        return _fernet().decrypt(blob)
    except InvalidToken as e:
        raise BackupError("Cannot decrypt the media archive: wrong key or corrupted archive.") from e


def restore_media(record: BackupRecord, dest=None) -> int:
    """Extract the media archive into MEDIA_ROOT, refusing anything that is not a plain file inside that folder. Never overwrites existing files."""
    root = Path(dest or settings.MEDIA_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True)
    n = 0
    with tarfile.open(fileobj=io.BytesIO(read_media(record)), mode="r:gz") as tar:
        for m in tar.getmembers():
            target = (root / m.name).resolve()
            if not m.isfile() or root not in target.parents:
                raise BackupError(f"Refusing unsafe archive member: {m.name[:80]}")
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(tar.extractfile(m).read())
            n += 1
    return n


def iter_objects(data: bytes):
    lines = data.decode().splitlines()
    return serializers.deserialize("jsonl", "\n".join(lines[1:]))


def verify_backup(record: BackupRecord) -> BackupRecord:
    """Prove the archive is readable and complete without touching live data."""
    try:
        if record.status != BackupRecord.Status.SUCCEEDED:
            raise BackupError("Only successful backups can be verified.")
        counts: Counter = Counter()
        for obj in iter_objects(read_archive(record)):
            counts[obj.object._meta.label_lower] += 1
        if dict(counts) != record.counts:
            raise BackupError("Row counts in the archive do not match what was recorded.")
        if record.media_object_key:
            with tarfile.open(fileobj=io.BytesIO(read_media(record)), mode="r:gz") as tar:
                if sum(1 for m in tar.getmembers() if m.isfile()) != record.media_files:
                    raise BackupError("The media archive does not contain the recorded number of files.")
        record.verify_ok, record.verify_error = True, ""
    except Exception as e:  # noqa: BLE001
        record.verify_ok, record.verify_error = False, f"{type(e).__name__}: {e}"[:300]
    record.verified_at = timezone.now()
    record.save(update_fields=["verify_ok", "verify_error", "verified_at"])
    return record


def restore_into_empty_database(record: BackupRecord | None = None, key: str = "") -> dict:
    """Load an archive into a database that has NO users or restaurants. Atomic: all or nothing."""
    from apps.accounts.models import User
    from apps.tenants.models import Restaurant

    if User.objects.exists() or Restaurant.unscoped_objects.exists():
        raise BackupError("Refusing to restore: the target database is not empty. Restore into a new, empty database.")
    data = read_archive(record) if record is not None else read_archive_by_key(key)
    n: Counter = Counter()
    with transaction.atomic(), connection.constraint_checks_disabled():
        for obj in iter_objects(data):
            obj.save()
            n[obj.object._meta.label_lower] += 1
        connection.check_constraints()
    if record is not None and dict(n) != record.counts:
        raise BackupError("Restored row counts differ from the backup's.")
    return dict(n)


def prune(now=None) -> int:
    """Delete archives older than the retention window, always keeping the newest BACKUP_KEEP_MIN successful ones."""
    now = now or timezone.now()
    good = list(BackupRecord.objects.filter(status="succeeded", pruned_at__isnull=True).order_by("-created_at", "-id"))
    cutoff = now - timedelta(days=settings.BACKUP_RETAIN_DAYS)
    removed = 0
    for rec in good[settings.BACKUP_KEEP_MIN:]:
        if rec.created_at < cutoff:
            try:
                st = _storage_for(rec)
                st.delete(rec.object_key)
                if rec.media_object_key:
                    st.delete(rec.media_object_key)
            except (BackupError, StorageError):
                continue
            rec.pruned_at = now
            rec.save(update_fields=["pruned_at"])
            removed += 1
    return removed


# ---- restore of the LIVE database, from the System page ---------------------------------------------------------------
MAINTENANCE_KEY = "platform-maintenance"
MAINTENANCE_SECONDS = 30 * 60


class RestoreRefused(BackupError):
    pass


def maintenance_on() -> bool:
    from django.core.cache import cache

    return bool(cache.get(MAINTENANCE_KEY))


def _wipe_and_load(data: bytes) -> dict:
    """Inside one transaction: delete every row of every backed-up table, load the archive, reset sequences. All or nothing."""
    from django.core.management.color import no_style

    models_ = backed_up_models()
    n: Counter = Counter()
    with connection.cursor() as cur:
        if connection.vendor == "postgresql":
            cur.execute("SET CONSTRAINTS ALL DEFERRED")  # Django creates DEFERRABLE foreign keys: they are checked once, at commit
        # rows of tables that are NOT in the archive but point at restored tables are removed or detached first
        cur.execute("UPDATE backups_backuprecord SET created_by_id = NULL")
        for table in ("django_admin_log", "core_idempotencykey", "token_blacklist_blacklistedtoken", "token_blacklist_outstandingtoken"):
            if table in connection.introspection.table_names():
                cur.execute(f"DELETE FROM {table}")
        cur.execute("UPDATE notifications_emaillog SET restaurant_id = NULL")
    all_models = [m for m in apps.get_models(include_auto_created=True) if m._meta.label_lower not in EXCLUDED and m._meta.app_label not in EXCLUDED_APPS and not m._meta.proxy]
    for model in all_models:  # includes many-to-many through tables
        model._base_manager.all()._raw_delete(model._base_manager.db)
    for obj in iter_objects(data):
        obj.save()
        n[obj.object._meta.label_lower] += 1
    if connection.vendor == "postgresql":
        with connection.cursor() as cur:
            for sql in connection.ops.sequence_reset_sql(no_style(), models_):
                cur.execute(sql)
    connection.check_constraints()
    return dict(n)


def restore_live(record: BackupRecord, requested_by: str) -> RestoreRecord:
    """Replace ALL platform data with the contents of a verified backup.

    Order of events (nothing irreversible happens before step 3):
      1. verify the chosen archive (checksum, decryption, parse, row counts);
      2. take and verify a safety snapshot of the current live data (a restore can itself be undone from it);
      3. switch on maintenance mode (every request except health checks answers 503);
      4. replace the data in one transaction, revoke every session;
      5. switch maintenance off, record the outcome.
    """
    from django.core.cache import cache
    from django.db.models import F

    from apps.accounts.models import User

    if RestoreRecord.objects.filter(status="running", started_at__gte=timezone.now() - timedelta(minutes=30)).exists():
        raise RestoreRefused("A restore is already running.")
    if record.status != BackupRecord.Status.SUCCEEDED or record.pruned_at:
        raise RestoreRefused("Only a successful backup that is still in storage can be restored.")
    job = RestoreRecord.objects.create(backup=record, requested_by=requested_by[:254])
    try:
        verified = verify_backup(record)
        if not verified.verify_ok:
            raise RestoreRefused(f"The backup did not verify: {verified.verify_error}")
        data = read_archive(record)
        safety = run_backup(BackupRecord.objects.create(kind="manual"))
        job.safety_backup = safety
        job.save(update_fields=["safety_backup"])
        if safety.status != BackupRecord.Status.SUCCEEDED or not verify_backup(safety).verify_ok:
            raise RestoreRefused("Could not take a verified safety snapshot of the current data, so nothing was changed.")
        cache.set(MAINTENANCE_KEY, 1, MAINTENANCE_SECONDS)
        try:
            with transaction.atomic():
                counts = _wipe_and_load(data)
                User.objects.update(token_version=F("token_version") + 1)  # everyone signs in again
        finally:
            cache.delete(MAINTENANCE_KEY)
        job.status, job.rows = RestoreRecord.Status.SUCCEEDED, sum(counts.values())
    except Exception as e:  # noqa: BLE001
        job.status, job.error = RestoreRecord.Status.FAILED, f"{type(e).__name__}: {e}"[:300]
    job.finished_at = timezone.now()
    job.save()
    return job
