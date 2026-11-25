from celery import shared_task

from . import service
from .models import BackupRecord


@shared_task
def run_backup_task(record_id):
    rec = BackupRecord.objects.get(pk=record_id)
    service.run_backup(rec)
    return rec.status


@shared_task
def scheduled_backup():
    rec = BackupRecord.objects.create(kind="scheduled")
    return service.run_backup(rec).status


@shared_task
def prune_backups():
    return service.prune()


@shared_task
def verify_latest():
    rec = BackupRecord.objects.filter(status="succeeded", pruned_at__isnull=True).first()
    return service.verify_backup(rec).verify_ok if rec else None
