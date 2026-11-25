import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

log = logging.getLogger(__name__)


class ProviderError(Exception):
    pass


class ConsoleProvider:
    """Dev/test only. Keeps messages in memory; logs the subject, never the body."""

    outbox: list = []

    def send(self, *, to, subject, html, sender_name, reply_to=None, text=""):
        self.outbox.append({"to": to, "subject": subject, "html": html, "text": text, "sender_name": sender_name, "reply_to": reply_to})
        log.info("console email queued to=%s subject=%s", to, subject)
        if settings.DEBUG:  # local development only: lets developers follow one-time links. Never runs in production.
            import re
            links = re.findall(r'href="(http[^"]+)"', html) + re.findall(r'letter-spacing:6px[^>]*>([A-Z0-9]{6})<', html)
            print(f"[dev email] to={to} subject={subject!r} links/codes={links}", flush=True)
        return f"console-{len(self.outbox)}"


class BrevoProvider:
    URL = "https://api.brevo.com/v3/smtp/email"

    def send(self, *, to, subject, html, sender_name, reply_to=None, text=""):
        if not settings.BREVO_API_KEY or not settings.BREVO_SENDER_EMAIL:
            raise ProviderError("Brevo is not configured (BREVO_API_KEY / BREVO_SENDER_EMAIL).")
        payload = {
            "sender": {"name": sender_name, "email": settings.BREVO_SENDER_EMAIL},
            "to": [{"email": to}],
            "subject": subject,
            "htmlContent": html,
        }
        if text:
            payload["textContent"] = text  # plain-text alternative: better deliverability and accessibility
        if reply_to:
            payload["replyTo"] = {"email": reply_to}
        req = urllib.request.Request(
            self.URL, data=json.dumps(payload).encode(), method="POST",
            headers={"api-key": settings.BREVO_API_KEY, "content-type": "application/json", "accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read() or b"{}").get("messageId", "")
        except urllib.error.HTTPError as exc:
            # 4xx (other than 429) will not succeed on retry, but keep one code path; the task caps retries.
            raise ProviderError(f"Brevo HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError("Brevo unreachable") from exc


def get_provider():
    return BrevoProvider() if settings.EMAIL_PROVIDER == "brevo" else ConsoleProvider()
