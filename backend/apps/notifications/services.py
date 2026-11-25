from django.conf import settings
from django.db import IntegrityError, transaction

from .models import EmailLog
from .tasks import send_email_task
from .templates import render_email


def html_to_text(html):
    """Plain-text alternative for the HTML body (links keep their address)."""
    import html as _h
    import re

    t = re.sub(r"(?is)<(style|script).*?</\1>", "", html)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</h2>|</tr>", "\n", t)
    t = re.sub(r'(?is)<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', lambda m: f"{re.sub('<[^>]+>', '', m.group(2))} ({m.group(1)})", t)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\n\s*\n+", "\n\n", _h.unescape(t)).strip()


def queue_email(template, to, context, *, restaurant=None, dedupe_key=None, branded=True):
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
    reply_to = (brand.contact_email or None) if brand else None
    dispatch = lambda: send_email_task.delay(entry.pk, subject, html, sender_name, reply_to, html_to_text(html))  # noqa: E731
    if settings.EMAIL_ENQUEUE_ON_COMMIT:
        transaction.on_commit(dispatch)  # never send mail for a transaction that rolled back
    else:
        dispatch()
    return entry
