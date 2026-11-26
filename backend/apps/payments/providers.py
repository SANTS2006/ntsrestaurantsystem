"""Payment provider abstraction.

Adding a provider = one class implementing ``BaseProvider`` + one entry in ``REGISTRY``.

Monime has two ways to collect: the hosted Checkout Session page (preferred: the customer is redirected there) and Payment Codes
(a USSD code the customer dials to pay with Orange Money or Afrimoney). If the checkout service fails, the adapter falls back to a
payment code, so customers can still pay; after a failure the checkout service is skipped for a few minutes, so nobody waits on it.

Monime: implemented from the official docs (docs.monime.io, API version caph.2025-08-23): hosted Checkout
Sessions (`POST /v1/checkout-sessions`, the customer is redirected to `redirectUrl` and picks card, bank, mobile
money or wallet on Monime's page), status by `GET /v1/checkout-sessions/{id}`, and signed webhooks
(`monime-signature: t=<unix>,v1=<base64 HMAC-SHA256 of "<t>_<raw body>">`). Monime has no refund API, so refunds of
Monime payments are made in the Monime dashboard and recorded here with their reference. It has NOT been exercised
against the live service from this codebase. Safety does not depend on that: a webhook is only a hint, and a payment
is never marked paid until Monime's own status endpoint, queried by the server, says the session is completed for
the right amount and currency.
"""
import base64
import hashlib
import hmac
import json
import logging
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache


log = logging.getLogger(__name__)


class ProviderError(Exception):
    pass


class IgnoredEvent(Exception):
    """A signed event we do not act on (acknowledged with 200 so the provider does not keep retrying)."""


@dataclass
class Created:
    provider_ref: str
    redirect_url: str = ""  # a hosted payment page to send the customer to ...
    ussd_code: str = ""  # ... or a code the customer dials on their phone


@dataclass
class RemoteStatus:
    status: str  # pending | succeeded | failed
    amount: Decimal
    currency: str


@dataclass
class Event:
    event_id: str
    event_type: str
    provider_ref: str


class BaseProvider:
    name = ""
    supports_refunds = True

    def create_payment(self, *, reference, amount, currency, phone, return_url, cancel_url="") -> Created:
        raise NotImplementedError

    def fetch_status(self, provider_ref) -> RemoteStatus:
        raise NotImplementedError

    def refund(self, *, provider_ref, reference, amount, currency) -> str:
        """Returns the provider refund id. Raises ProviderError on failure."""
        raise NotImplementedError

    def verify_webhook(self, headers, raw_body: bytes) -> bool:
        raise NotImplementedError

    def parse_event(self, body: dict) -> Event:
        raise NotImplementedError


def _hmac(secret: str, payload: bytes) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


class SimulatedProvider(BaseProvider):
    """Development/test only (refused in production settings). State lives in the cache."""

    name = "simulated"

    @staticmethod
    def _key(ref):
        return f"sim-payment:{ref}"

    def create_payment(self, *, reference, amount, currency, phone, return_url, cancel_url=""):
        ref = f"SIM-{uuid.uuid4().hex[:16]}"
        cache.set(self._key(ref), {"status": "pending", "amount": str(amount), "currency": currency}, 3600)
        return Created(provider_ref=ref, redirect_url="")

    def set_outcome(self, ref, status, amount=None):
        data = cache.get(self._key(ref))
        if data is None:
            raise ProviderError("Unknown simulated payment.")
        data["status"] = status
        if amount is not None:
            data["amount"] = str(amount)
        cache.set(self._key(ref), data, 3600)

    def fetch_status(self, provider_ref):
        data = cache.get(self._key(provider_ref))
        if data is None:
            raise ProviderError("Unknown payment.")
        return RemoteStatus(data["status"], Decimal(data["amount"]), data["currency"])

    def refund(self, *, provider_ref, reference, amount, currency):
        return f"SIMREF-{uuid.uuid4().hex[:12]}"

    def sign(self, raw: bytes) -> str:
        return _hmac(settings.SIMULATED_WEBHOOK_SECRET, raw)

    def verify_webhook(self, headers, raw_body):
        sig = headers.get("X-Signature", "")
        return bool(sig) and hmac.compare_digest(sig, self.sign(raw_body))

    def parse_event(self, body):
        return Event(str(body["id"]), str(body.get("type", "")), str(body["data"]["provider_ref"]))


def _monime_reason(exc) -> str:
    """Monime's own explanation of a refused request, for the server log (never shown to customers). Contains no credentials."""
    try:
        err = json.loads(exc.read() or b"{}").get("error") or {}
        parts = [str(err.get(k)) for k in ("reason", "message", "code") if err.get(k)]
        return (": " + " | ".join(parts))[:300] if parts else ""
    except Exception:  # noqa: BLE001
        return ""


class MonimeProvider(BaseProvider):
    name = "monime"
    supports_refunds = False  # no refund endpoint in the API: refunds are made in the Monime dashboard
    MINOR = {"SLE": 100}  # the platform trades in Sierra Leone leones only; amounts are sent in the minor unit (cents)
    ATTEMPTS = 3
    RETRY_WAIT = 1.0  # seconds, multiplied by the attempt number
    CHECKOUT_TIMEOUT = 8  # seconds: the customer is waiting; past this we offer the dial code instead
    CHECKOUT_PAUSE = 300  # seconds the checkout service is skipped after it failed
    CHECKOUT_DOWN_KEY = "monime-checkout-down"
    CODE_LIFETIME = "30m"

    def _cfg(self):
        c = settings
        if not (c.MONIME_ACCESS_TOKEN and c.MONIME_SPACE_ID):
            raise ProviderError("Monime is not configured (MONIME_ACCESS_TOKEN / MONIME_SPACE_ID).")
        return c

    def _request(self, method, path, payload=None, idempotency_key="", timeout=20, attempts=None):
        attempts = attempts or self.ATTEMPTS
        c = self._cfg()
        headers = {"Authorization": f"Bearer {c.MONIME_ACCESS_TOKEN}", "Monime-Space-Id": c.MONIME_SPACE_ID, "Monime-Version": c.MONIME_VERSION,
                   "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "RestaurantPlatform/1.0"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key[:100]
        req = urllib.request.Request(c.MONIME_BASE_URL.rstrip("/") + path, method=method, headers=headers,
                                     data=json.dumps(payload).encode() if payload is not None else None)
        # A gateway error (Monime briefly unavailable) is retried: reads are harmless and creating carries an Idempotency-Key,
        # so a retry can never make a second payment.
        for attempt in range(1, attempts + 1):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = json.loads(resp.read() or b"{}")
                break
            except urllib.error.HTTPError as exc:
                if exc.code in (502, 503, 504) and attempt < attempts and (method == "GET" or idempotency_key):
                    time.sleep(self.RETRY_WAIT * attempt)
                    continue
                raise ProviderError(f"Monime HTTP {exc.code}{_monime_reason(exc)}") from exc
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                raise ProviderError("Monime unreachable or returned invalid data") from exc
        if not isinstance(body, dict) or body.get("success") is not True or not isinstance(body.get("result"), dict):
            raise ProviderError("Monime returned an unexpected response.")
        return body["result"]

    def create_payment(self, *, reference, amount, currency, phone, return_url, cancel_url=""):
        cur = currency.upper()
        if cur not in self.MINOR:
            raise ProviderError("Payments are made in SLE only.")
        value = int((Decimal(amount) * self.MINOR[cur]).to_integral_value())
        if value <= 0:
            raise ProviderError("Invalid amount.")
        self._cfg()
        if not cache.get(self.CHECKOUT_DOWN_KEY):
            try:
                return self._checkout_session(reference, cur, value, return_url, cancel_url or return_url)
            except ProviderError as exc:
                log.error("Monime checkout page unavailable, offering a dial code instead: %s", exc)
                cache.set(self.CHECKOUT_DOWN_KEY, 1, self.CHECKOUT_PAUSE)
        return self._payment_code(reference, cur, value)

    def _checkout_session(self, reference, cur, value, return_url, cancel_url):
        # One line item carrying the whole amount: the order total was already computed (and taxed) by this server.
        result = self._request("POST", "/checkout-sessions", {
            "name": f"Order payment {reference}"[:150], "reference": reference[:255], "successUrl": return_url[:255], "cancelUrl": cancel_url[:255],
            "lineItems": [{"type": "custom", "name": "Order total", "quantity": 1, "price": {"currency": cur, "value": value}}],
            "metadata": {"reference": reference[:100]}}, idempotency_key=reference, timeout=self.CHECKOUT_TIMEOUT, attempts=1)
        ref, url = str(result.get("id") or ""), str(result.get("redirectUrl") or "")
        if not ref or not url.startswith("https://"):
            raise ProviderError("Monime response had no checkout session or redirect URL.")
        return Created(provider_ref=ref, redirect_url=url)

    def _payment_code(self, reference, cur, value):
        """A one-time USSD code for exactly this amount (Orange Money / Afrimoney)."""
        result = self._request("POST", "/payment-codes", {
            "name": f"Order payment {reference}"[:64], "mode": "one_time", "duration": self.CODE_LIFETIME, "reference": reference[:64],
            "amount": {"currency": cur, "value": value}, "metadata": {"reference": reference[:100]}}, idempotency_key=f"{reference}-code")
        ref, code = str(result.get("id") or ""), str(result.get("ussdCode") or "")
        if not ref.startswith("pmc-") or not re.fullmatch(r"\*[0-9*]+#", code):
            raise ProviderError("Monime response had no usable payment code.")
        return Created(provider_ref=ref, ussd_code=code)

    def _code_status(self, provider_ref):
        r = self._request("GET", f"/payment-codes/{provider_ref}")
        raw = str(r.get("status", "")).lower()
        status = "succeeded" if raw == "completed" else "failed" if raw in ("cancelled", "expired") else "pending"
        try:
            cur = str(r["amount"]["currency"]).upper()
            total = Decimal(int(r["amount"]["value"])) / self.MINOR[cur]
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            log.error("Monime payment code %s has an unexpected shape; fields: %s", provider_ref, sorted(r))
            raise ProviderError("Monime payment code response has no usable amount.") from exc
        return RemoteStatus(status, total.quantize(Decimal("0.01")), cur)

    def fetch_status(self, provider_ref):
        if provider_ref.startswith("pmc-"):
            return self._code_status(provider_ref)
        r = self._request("GET", f"/checkout-sessions/{provider_ref}")
        raw = str(r.get("status", "")).lower()
        status = "succeeded" if raw == "completed" else "failed" if raw in ("cancelled", "expired") else "pending"
        found = r.get("lineItems") or []
        items = (found.get("data") or []) if isinstance(found, dict) else found  # the item list may be wrapped in {"data": [...]}
        try:
            cur = str(items[0]["price"]["currency"]).upper()
            minor = self.MINOR[cur]
            total = sum((Decimal(int(i["price"]["value"])) * int(i.get("quantity", 1)) for i in items), Decimal(0)) / minor
        except (KeyError, IndexError, TypeError, ValueError, ArithmeticError) as exc:
            log.error("Monime session %s has an unexpected shape; fields: %s; lineItems: %s", provider_ref, sorted(r), str(found)[:300])
            raise ProviderError("Monime session response has no usable line items.") from exc
        return RemoteStatus(status, total.quantize(Decimal("0.01")), cur)

    def refund(self, *, provider_ref, reference, amount, currency):
        raise ProviderError("Monime refunds are made in the Monime dashboard.")

    def verify_webhook(self, headers, raw_body):
        """monime-signature: t=<unix>,v1=<base64(HMAC-SHA256(secret, "<t>_<raw body>"))>; rejects stale or future timestamps."""
        secret = settings.MONIME_WEBHOOK_SECRET
        header = headers.get("monime-signature", "")
        if not secret or not header:
            return False  # never accept unsigned webhooks
        parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
        ts, sig = parts.get("t", ""), parts.get("v1", "")
        if not ts.isdigit() or not sig:
            return False
        now = time.time()
        if now - int(ts) > 300 or int(ts) - now > 60:
            return False
        expected = base64.b64encode(hmac.new(secret.encode(), ts.encode() + b"_" + raw_body, hashlib.sha256).digest()).decode()
        return hmac.compare_digest(sig, expected)

    def parse_event(self, body):
        ev, obj = body.get("event") or {}, body.get("object") or {}
        name = str(ev.get("name", ""))
        if not name.startswith(("checkout_session.", "payment_code.")):
            raise IgnoredEvent(name)  # payments, payouts, transfers... are not ours to act on
        if not ev.get("id") or not obj.get("id"):
            raise ValueError("unrecognised event")
        return Event(str(ev["id"]), name, str(obj["id"]))


REGISTRY = {"simulated": SimulatedProvider, "monime": MonimeProvider}


def get_provider(name=None) -> BaseProvider:
    name = name or settings.PAYMENT_PROVIDER
    if name == "simulated" and not (settings.DEBUG or settings.TESTING_PAYMENTS):
        raise ProviderError("The simulated provider is disabled outside development.")
    cls = REGISTRY.get(name)
    if cls is None:
        raise ProviderError(f"Unknown payment provider: {name}")
    return cls()


def online_payments_available() -> bool:
    try:
        p = get_provider()
        return p.name != "monime" or bool(settings.MONIME_ACCESS_TOKEN and settings.MONIME_SPACE_ID and settings.MONIME_WEBHOOK_SECRET)
    except ProviderError:
        return False
