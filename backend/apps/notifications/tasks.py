from celery import shared_task
from django.utils import timezone

from .models import EmailLog
from .providers import ProviderError, get_provider


@shared_task(bind=True, max_retries=5, acks_late=True)
def send_email_task(self, log_id, subject, html, sender_name, reply_to=None, text=""):
    entry = EmailLog.objects.get(pk=log_id)
    if entry.status == EmailLog.Status.SENT:  # redelivered task: never send twice
        return entry.provider_message_id
    try:
        message_id = get_provider().send(to=entry.to_email, subject=subject, html=html,
                                         sender_name=sender_name, reply_to=reply_to, text=text)
    except ProviderError as exc:
        entry.attempts += 1
        entry.error = str(exc)[:300]
        exhausted = self.request.retries >= self.max_retries
        entry.status = EmailLog.Status.FAILED if exhausted else EmailLog.Status.RETRYING
        entry.save(update_fields=["attempts", "error", "status"])
        if exhausted:
            raise
        raise self.retry(exc=exc, countdown=min(30 * 2 ** self.request.retries, 900))
    entry.attempts += 1
    entry.status, entry.provider_message_id, entry.sent_at, entry.error = EmailLog.Status.SENT, message_id or "", timezone.now(), ""
    entry.save(update_fields=["attempts", "status", "provider_message_id", "sent_at", "error"])
    return message_id
