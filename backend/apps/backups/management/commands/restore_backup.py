from django.core.management.base import BaseCommand, CommandError

from apps.backups import service
from apps.backups.models import BackupRecord
from apps.backups.storage import get_storage


class Command(BaseCommand):
    help = ("List, verify or restore backups. Restore loads ONLY into an empty database and is never available through the web API. "
            "Disaster recovery: point DATABASE_URL at a new empty database, run migrate, then "
            "`restore_backup --list`, then `restore_backup --key <object key> --apply --confirm RESTORE`.")

    def add_arguments(self, parser):
        parser.add_argument("record_id", type=int, nargs="?", help="BackupRecord id (shown on the System page) in this database.")
        parser.add_argument("--list", action="store_true", help="List archive object keys in the configured storage.")
        parser.add_argument("--key", default="", help="Object key to restore from when this database has no BackupRecord rows.")
        parser.add_argument("--media", action="store_true", help="Also restore uploaded files into MEDIA_ROOT (with --apply; existing files are never overwritten).")
        parser.add_argument("--apply", action="store_true", help="Actually load the data. Without it only verification runs.")
        parser.add_argument("--confirm", default="", help="Must be the record id, or the word RESTORE when --key is used.")

    def handle(self, *args, **opts):
        if opts["list"]:
            for k in get_storage().list():
                self.stdout.write(k)
            return
        rec = None
        if opts["record_id"] is not None:
            rec = BackupRecord.objects.filter(pk=opts["record_id"]).first()
            if rec is None:
                raise CommandError("No such backup record in this database. In a new database use --key.")
        elif not opts["key"]:
            raise CommandError("Give a record id or --key (or --list).")
        expected = str(rec.pk) if rec else "RESTORE"
        try:
            if not opts["apply"]:
                if rec is None:
                    service.read_archive_by_key(opts["key"])
                    self.stdout.write(self.style.SUCCESS("Archive decrypted and readable."))
                    return
                r = service.verify_backup(rec)
                self.stdout.write(self.style.SUCCESS("Backup verified.") if r.verify_ok else self.style.ERROR(f"Verification failed: {r.verify_error}"))
                return
            if opts["confirm"] != expected:
                raise CommandError(f"Add --confirm {expected} to confirm you are restoring into THIS database.")
            counts = service.restore_into_empty_database(rec, opts["key"])
            if opts["media"] and rec is not None and rec.media_object_key:
                self.stdout.write(f"Restored {service.restore_media(rec)} media file(s).")
        except service.BackupError as e:
            raise CommandError(str(e))
        self.stdout.write(self.style.SUCCESS(f"Restored {sum(counts.values())} rows across {len(counts)} tables."))
