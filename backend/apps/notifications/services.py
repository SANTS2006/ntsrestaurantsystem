import logging
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.db import IntegrityError, close_old_connections, transaction

from .models import EmailLog
from .tasks import send_email_task
from .templates import render_email


log = logging.getLogger(__name__)
# Without a queue server, mail leaves on one background thread so that nobody waits for it (a bulk payroll run sends many).
_sender = ThreadPoolExecutor(max_workers=1, thread_name_prefix="email")


def _send_in_background(*args):
    close_old_connections()
    try:
        send_email_task.apply(args=list(args))
    except Exception:  # noqa: BLE001 - the delivery record keeps the failure; the thread must live on
        log.exception("could not send an email in the background")
    finally:
        close_old_connections()


def _dispatch(*args):
    if settings.EMAIL_IN_BACKGROUND:
        _sender.submit(_send_in_background, *args)
    else:
        send_email_task.delay(*args)


def html_to_text(html):
    """Plain-text alternative for the HTML body (links keep their address)."""
    import html as _h
    import re

    t = re.sub(r"(?is)<(style|script).*?</\1>", "", html)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</h2>|</tr>", "\n", t)
    t = re.sub(r'(?is)<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', lambda m: f"{re.sub('<[^>]+>', '', m.group(2))} ({m.group(1)})", t)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\n\s*\n+", "\n\n", _h.unescape(t)).strip()


def queue_email(template, to, context, *, restaurant=None, dedupe_key=None, branded=True, reply_to=None):
    """Render and enqueue an email (sent by Celery, never inline in a request).

    Returns the EmailLog, or None when ``dedupe_key`` was already used (duplicate request/webhook).
    """
    brand = restaurant if branded else None  # branded=False: platform-originated mail about a restaurant
    subject, html = render_email(template, context, brand)
    try:
        with transaction.atomic():
            entry = EmailLog.objects.create(restaurant=restaurant, template=template, to_email=to, dedupe_key=dedupe_key)
    except IntegrityError:
        return None
    sender_name = brand.name if brand else settings.BREVO_SENDER_NAME
    reply_to = reply_to or ((brand.contact_email or None) if brand else None)
    dispatch = lambda: _dispatch(entry.pk, subject, html, sender_name, reply_to, html_to_text(html))  # noqa: E731
    if settings.EMAIL_ENQUEUE_ON_COMMIT:
        transaction.on_commit(dispatch)  # never send mail for a transaction that rolled back
    else:
        dispatch()
    return entry
