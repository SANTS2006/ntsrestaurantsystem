from celery import shared_task

from .services import reconcile_pending


@shared_task
def reconcile_payments():
    """Schedule with celery beat every few minutes: settles payments whose webhook never arrived."""
    return reconcile_pending()
