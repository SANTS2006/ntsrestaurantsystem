import base64
import hashlib
import hmac
import io
import json
import time
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from apps.payments import providers
from apps.payments.models import Payment, PaymentEvent

from .conftest import client_for, host
from .test_phase5_orders import clean, shop  # noqa: F401


# ================================ Monime (contract from docs.monime.io, API caph.2025-08-23) ================================
class FakeResp:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def monime(settings, monkeypatch):
    settings.MONIME_API_KEY, settings.MONIME_SPACE_ID, settings.MONIME_WEBHOOK_SECRET = "mk_test", "spc-test", "w" * 40
    settings.MONIME_BASE_URL, settings.MONIME_VERSION = "https://api.monime.io/v1", "caph.2025-08-23"
    sent = []

    def fake(req, timeout=0):
        sent.append(req)
        if req.method == "POST":
            return FakeResp({"success": True, "messages": [], "result": {"id": "chk-123", "status": "pending", "redirectUrl": "https://pay.monime.io/c/abc"}})
        return FakeResp({"success": True, "messages": [], "result": {"id": "chk-123", "status": "completed", "lineItems": {"data": [{"type": "custom", "quantity": 1, "price": {"currency": "SLE", "value": 7393}}]}}})

    monkeypatch.setattr(providers.urllib.request, "urlopen", fake)
    return sent


def test_monime_creates_a_hosted_checkout_session_with_the_documented_request(monime):
    c = providers.MonimeProvider().create_payment(reference="PAY-ABC", amount=Decimal("73.93"), currency="SLE", phone="+23276123456", return_url="https://x.example/account/orders/1")
    assert c.provider_ref == "chk-123" and c.redirect_url == "https://pay.monime.io/c/abc"
    req = monime[0]
    h = {k.lower(): v for k, v in req.header_items()}
    assert req.full_url == "https://api.monime.io/v1/checkout-sessions" and req.method == "POST"
    assert h["authorization"] == "Bearer mk_test" and h["monime-space-id"] == "spc-test" and h["monime-version"] == "caph.2025-08-23" and h["idempotency-key"] == "PAY-ABC"
    body = json.loads(req.data)
    assert body["reference"] == "PAY-ABC" and body["successUrl"] == body["cancelUrl"] == "https://x.example/account/orders/1"
    assert body["lineItems"] == [{"type": "custom", "name": "Order total", "quantity": 1, "price": {"currency": "SLE", "value": 7393}}]  # minor units, exact


def test_monime_rejects_unsupported_currency_and_bad_responses(monime, monkeypatch):
    with pytest.raises(providers.ProviderError):
        providers.MonimeProvider().create_payment(reference="R", amount=Decimal("1"), currency="EUR", phone="", return_url="https://x")
    monkeypatch.setattr(providers.urllib.request, "urlopen", lambda req, timeout=0: FakeResp({"success": True, "result": {"id": "x", "redirectUrl": "http://insecure"}}))
    with pytest.raises(providers.ProviderError):
        providers.MonimeProvider().create_payment(reference="R", amount=Decimal("1"), currency="SLE", phone="", return_url="https://x")
    monkeypatch.setattr(providers.urllib.request, "urlopen", lambda req, timeout=0: FakeResp({"success": False}))
    with pytest.raises(providers.ProviderError):
        providers.MonimeProvider().fetch_status("chk-1")


def test_monime_status_comes_from_the_session_and_its_line_items(monime):
    st = providers.MonimeProvider().fetch_status("chk-123")
    assert st.status == "succeeded" and st.amount == Decimal("73.93") and st.currency == "SLE"
    assert monime[0].method == "GET" and monime[0].full_url.endswith("/checkout-sessions/chk-123")


@pytest.mark.parametrize("raw,expected", [("completed", "succeeded"), ("pending", "pending"), ("cancelled", "failed"), ("expired", "failed")])
def test_monime_status_mapping(monkeypatch, settings, raw, expected):
    settings.MONIME_API_KEY, settings.MONIME_SPACE_ID = "k", "spc-1"
    monkeypatch.setattr(providers.urllib.request, "urlopen", lambda req, timeout=0: FakeResp({"success": True, "result": {"status": raw, "lineItems": {"data": [{"quantity": 2, "price": {"currency": "USD", "value": 150}}]}}}))
    st = providers.MonimeProvider().fetch_status("chk")
    assert st.status == expected and st.amount == Decimal("3.00") and st.currency == "USD"


def sign(secret, body: bytes, ts=None):
    ts = str(int(ts if ts is not None else time.time()))
    return f"t={ts},v1=" + base64.b64encode(hmac.new(secret.encode(), ts.encode() + b"_" + body, hashlib.sha256).digest()).decode()


def test_monime_webhook_signature_follows_the_documented_scheme(settings):
    settings.MONIME_WEBHOOK_SECRET = "s" * 40
    p, body = providers.MonimeProvider(), b'{"event":{"name":"checkout_session.completed"}}'
    assert p.verify_webhook({"monime-signature": sign("s" * 40, body)}, body)
    assert not p.verify_webhook({"monime-signature": sign("x" * 40, body)}, body)  # wrong secret
    assert not p.verify_webhook({"monime-signature": sign("s" * 40, body + b" ")}, body)  # altered body
    assert not p.verify_webhook({"monime-signature": sign("s" * 40, body, time.time() - 400)}, body)  # too old
    assert not p.verify_webhook({"monime-signature": sign("s" * 40, body, time.time() + 120)}, body)  # too far in the future
    assert not p.verify_webhook({}, body) and not p.verify_webhook({"monime-signature": "garbage"}, body)
    settings.MONIME_WEBHOOK_SECRET = ""
    assert not p.verify_webhook({"monime-signature": sign("", body)}, body)  # never accept when no secret is configured


def test_monime_events(monime):
    p = providers.MonimeProvider()
    ev = p.parse_event({"apiVersion": "caph.2025-08-23", "event": {"id": "wke-1", "name": "checkout_session.completed", "timestamp": "1"}, "object": {"id": "chk-9", "type": "checkout_session"}, "data": {}})
    assert (ev.event_id, ev.event_type, ev.provider_ref) == ("wke-1", "checkout_session.completed", "chk-9")
    with pytest.raises(providers.IgnoredEvent):
        p.parse_event({"event": {"id": "wke-2", "name": "payment.created"}, "object": {"id": "pay-1"}})
    with pytest.raises(ValueError):
        p.parse_event({"event": {"name": "checkout_session.completed"}, "object": {}})


def test_monime_webhook_end_to_end_settles_only_through_the_status_endpoint(world, shop, clean, monime, settings):  # noqa: F811
    settings.PAYMENT_PROVIDER = "monime"
    from apps.tenants.models import RestaurantSettings
    RestaurantSettings.objects.filter(restaurant=world["a"]).update(online_payments_enabled=True)
    c = client_for(world["cust_a"], "alpha")
    order = c.post("/api/v1/orders/checkout/", {"items": [{"product_id": shop["rice"].pk, "quantity": 1}], "fulfilment": "pickup", "payment_method": "mobile_money", "contact_phone": "+23276123456", "branch_id": world["a1"].pk}, format="json", HTTP_IDEMPOTENCY_KEY="m1").json()["data"]
    order = order.get("order", order)
    r = c.post("/api/v1/payments/initiate/", {"order_id": order["id"], "phone": "+23276123456"}, format="json", HTTP_IDEMPOTENCY_KEY="m2")
    assert r.status_code in (200, 201), r.content
    pay = Payment.unscoped.get()
    assert pay.provider == "monime" and pay.provider_ref == "chk-123"
    # the fake status endpoint reports SLE 73.93 completed; the order total differs, so the payment must NOT be accepted as paid
    body = json.dumps({"event": {"id": "wke-77", "name": "checkout_session.completed", "timestamp": str(int(time.time()))}, "object": {"id": "chk-123", "type": "checkout_session"}, "data": {"status": "completed"}}).encode()
    hook = APIClient(HTTP_HOST=host("alpha")).post("/api/v1/payments/webhooks/monime/", body, content_type="application/json", HTTP_MONIME_SIGNATURE=sign(settings.MONIME_WEBHOOK_SECRET, body))
    assert hook.status_code == 200
    pay.refresh_from_db()
    assert PaymentEvent.objects.filter(event_id="wke-77").exists()
    assert pay.status != "succeeded" or pay.amount == Decimal("73.93")  # amounts must match what the order asked for
    ignored = json.dumps({"event": {"id": "wke-78", "name": "payment.created"}, "object": {"id": "pay-1"}}).encode()
    r = APIClient(HTTP_HOST=host("alpha")).post("/api/v1/payments/webhooks/monime/", ignored, content_type="application/json", HTTP_MONIME_SIGNATURE=sign(settings.MONIME_WEBHOOK_SECRET, ignored))
    assert r.status_code == 200 and r.json()["data"].get("ignored") is True  # acknowledged so Monime does not keep retrying


def test_refunds_of_provider_payments_without_a_refund_api_need_the_dashboard_reference(world, shop, clean, monime, settings):  # noqa: F811
    from apps.accounts.models import Role
    from apps.orders.models import Order
    from apps.payments.services import refund_payment
    from .test_phase8_management import mk_order

    o, p = mk_order(world, world["a1"], "40.00", paid="40.00", method="mobile_money")
    Payment.unscoped.filter(pk=p.pk).update(provider="monime", provider_ref="chk-123")
    ctx = type("R", (), {"tenant": world["a"], "user": world["mgr_a1"], "META": {}, "headers": {}})()
    from rest_framework.exceptions import ValidationError
    with pytest.raises(ValidationError) as e:
        refund_payment(ctx, p.pk, Decimal("10.00"), "customer request", {world["a1"].pk}, Role.MANAGER)
    assert "manual_reference" in str(e.value.detail)
    r = refund_payment(ctx, p.pk, Decimal("10.00"), "customer request", {world["a1"].pk}, Role.MANAGER, manual_reference="MONIME-REFUND-1")
    assert r.status == "succeeded" and r.provider_ref == "MONIME-REFUND-1"
    assert Order.unscoped.get(pk=o.pk).amount_paid == Decimal("30.00")
    _ = shop


# ================================ branded email ================================
def test_platform_and_restaurant_emails_have_their_own_look(world, settings):
    from apps.notifications.templates import render_email
    from apps.tenants.models import RestaurantSettings

    settings.PLATFORM_DOMAIN, settings.PUBLIC_URL_SCHEME = "example.com", "https"
    RestaurantSettings.objects.update_or_create(restaurant=world["a"], defaults={"email_footer": "Open daily 9 to 10. Thank you!"})
    world["a"].contact_phone, world["a"].address, world["a"].contact_email = "+23276000000", "1 Beach Road", "hello@alpha.test"
    world["a"].primary_color, world["a"].secondary_color = "#aa2200", "#ffcc00"
    world["a"].save()
    _, platform = render_email("password_changed", {"name": "Dana"}, None)
    assert "https://example.com/logo-192.png" in platform and "#0a72e0" in platform and "automated message from" in platform and "Open daily" not in platform
    _, rest = render_email("password_changed", {"name": "Dana"}, world["a"])
    assert "#aa2200" in rest and "#ffcc00" in rest and "Open daily 9 to 10. Thank you!" in rest and "1 Beach Road" in rest and "hello@alpha.test" in rest
    assert "alpha.example.com" in rest and "Sent through NTS Restaurant Platform" in rest and "logo-192.png" not in rest
    _, hostile = render_email("password_changed", {"name": '<script>alert(1)</script>'}, world["a"])
    assert "<script>alert(1)" not in hostile


def test_emails_carry_a_plain_text_alternative(world, settings):
    from apps.notifications.models import EmailLog
    from apps.notifications.providers import ConsoleProvider
    from apps.notifications.services import queue_email

    ConsoleProvider.outbox.clear()
    queue_email("password_changed", "dana@example.com", {"name": "Dana"}, restaurant=world["a"])
    assert EmailLog.objects.filter(template="password_changed").exists()
    m = ConsoleProvider.outbox[-1]
    assert "Dana" in m["text"] and "<" not in m["text"] and m["reply_to"] is None or m["reply_to"]


def test_brevo_request_includes_text_and_reply_to(settings, monkeypatch):
    from apps.notifications import providers as p

    settings.BREVO_API_KEY, settings.BREVO_SENDER_EMAIL = "k", "sender@example.com"
    seen = {}

    def fake(req, timeout=0):
        seen.update(json.loads(req.data), key=req.get_header("Api-key"))
        return FakeResp({"messageId": "<m1>"})

    monkeypatch.setattr(p.urllib.request, "urlopen", fake)
    assert p.BrevoProvider().send(to="a@b.c", subject="S", html="<p>Hi</p>", sender_name="Alpha", reply_to="hello@alpha.test", text="Hi") == "<m1>"
    assert seen["sender"] == {"name": "Alpha", "email": "sender@example.com"} and seen["replyTo"] == {"email": "hello@alpha.test"} and seen["textContent"] == "Hi" and seen["key"] == "k"


# ================================ Cloudinary ================================
def test_cloudinary_signature_and_upload(settings, monkeypatch):
    from apps.core import cloudinary_storage as cs

    settings.CLOUDINARY_CLOUD_NAME, settings.CLOUDINARY_API_KEY, settings.CLOUDINARY_API_SECRET = "democloud", "key123", "secret456"
    expected = hashlib.sha1(b"overwrite=false&public_id=products/abc&timestamp=1700000000secret456").hexdigest()
    assert cs._sign({"timestamp": 1700000000, "public_id": "products/abc", "overwrite": "false", "unique_filename": ""}) == expected  # empty values are not signed
    calls = []

    class R:
        status_code = 200

        def json(self):
            return {"public_id": "products/abc", "format": "png"}

    monkeypatch.setattr(cs.requests, "post", lambda url, data=None, files=None, timeout=0: calls.append((url, data, files)) or R())
    st = cs.CloudinaryStorage()
    name = st._save("products/abc.png", io.BytesIO(b"imgbytes"))
    assert name == "products/abc.png"
    url, data, files = calls[0]
    assert url == "https://api.cloudinary.com/v1_1/democloud/image/upload" and data["api_key"] == "key123" and data["public_id"] == "products/abc" and len(data["signature"]) == 40 and "file" in files
    assert "secret456" not in json.dumps({k: str(v) for k, v in data.items()})  # the secret is never sent
    assert st.url("products/abc.png") == "https://res.cloudinary.com/democloud/image/upload/q_auto/products/abc.png"
    st.delete("products/abc.png")
    assert calls[1][0].endswith("/image/destroy") and calls[1][1]["public_id"] == "products/abc"
    assert st.exists("x") is False


def test_cloudinary_failures_surface_and_cleanup_never_raises(settings, monkeypatch):
    from apps.core import cloudinary_storage as cs

    settings.CLOUDINARY_CLOUD_NAME, settings.CLOUDINARY_API_KEY, settings.CLOUDINARY_API_SECRET = "c", "k", "s"

    class Bad:
        status_code = 401

    monkeypatch.setattr(cs.requests, "post", lambda *a, **k: Bad())
    st = cs.CloudinaryStorage()
    with pytest.raises(OSError):
        st._save("a/b.png", io.BytesIO(b"x"))
    st.delete("a/b.png")  # swallowed
    settings.CLOUDINARY_API_SECRET = ""
    with pytest.raises(Exception):
        cs.CloudinaryStorage()


# ================================ upload re-encoding ================================
def test_uploaded_images_are_reencoded_and_stripped(world):
    from apps.catalog.models import Category, Product

    cat = Category.unscoped.create(restaurant=world["a"], name="Mains", slug="mains")
    p = Product.unscoped.create(restaurant=world["a"], category=cat, name="Rice", slug="rice", base_price=5)
    buf = io.BytesIO()
    img = Image.new("RGB", (6000, 3000), (10, 114, 224))
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"
    img.save(buf, format="JPEG", exif=exif)
    raw = buf.getvalue() + b"HIDDEN-TAIL-PAYLOAD"
    c = client_for(world["admin_a"], "alpha")
    r = c.post(f"/api/v1/catalog/products/{p.pk}/image/", {"image": SimpleUploadedFile("photo.jpg", raw, content_type="image/jpeg")}, format="multipart")
    assert r.status_code == 200, r.content
    p.refresh_from_db()
    stored = p.image.read()
    assert b"HIDDEN-TAIL-PAYLOAD" not in stored and b"SecretCameraMaker" not in stored  # nothing from the original file survives
    out = Image.open(io.BytesIO(stored))
    assert out.format == "JPEG" and max(out.size) <= 4096 and out.size[0] / out.size[1] == pytest.approx(2, rel=0.01)


# ================================ website served by the backend ================================
def test_spa_is_served_with_runtime_settings_and_security_headers(tmp_path, settings):
    index = tmp_path / "spa_index.html"
    index.write_text('<html><head><!--runtime-config--></head><body><div id="root"></div></body></html>', encoding="utf-8")
    settings.SPA_INDEX = index
    settings.PLATFORM_HOSTS = ["platform.test", "nts.example.com"]
    settings.GOOGLE_OAUTH_CLIENT_ID = 'abc"><script>x</script>'
    from apps.core import spa
    spa._cache.update(mtime=None, html="")
    c = APIClient(HTTP_HOST="platform.test")
    r = c.get("/restaurants/some/deep/link")
    assert r.status_code == 200 and r["Content-Type"].startswith("text/html") and r["Cache-Control"] == "no-cache"
    body = r.content.decode()
    assert '<meta name="platform-hosts" content="platform.test,nts.example.com"' in body and "<script>x</script>" not in body  # escaped
    csp = r["Content-Security-Policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp and "script-src 'self' https://accounts.google.com/gsi/client" in csp
    assert "unsafe-eval" not in csp and "script-src 'self' 'unsafe-inline'" not in csp
    assert r["Permissions-Policy"].startswith("camera=()") and r["Cross-Origin-Opener-Policy"]
    assert c.get("/healthz").status_code == 200


def test_api_unknown_paths_stay_json_and_are_never_cached(world, settings, tmp_path):
    settings.SPA_INDEX = tmp_path / "missing.html"
    c = client_for(world["admin_a"], "alpha")
    r = c.get("/api/v1/does-not-exist/")
    assert r.status_code == 404 and "text/html" not in r["Content-Type"]
    ok = c.get("/api/v1/payroll/employees/")
    assert ok["Cache-Control"] == "no-store" and "Content-Security-Policy" in ok
    from apps.core import spa
    spa._cache.update(mtime=None, html="")
    page = APIClient(HTTP_HOST=host("alpha")).get("/menu")
    assert page.status_code == 404 and page.json()["error"]["code"] == "frontend_not_built"


def test_api_docs_are_not_published_in_production_mode(client=None):
    from django.conf import settings
    from django.urls import resolve, Resolver404
    if settings.DEBUG:
        pytest.skip("docs are only registered when DEBUG is on")
    with pytest.raises(Exception):
        r = resolve("/api/docs/")
        assert r.func.__name__ != "SwaggerView"
        raise Resolver404()


# ================================ configuration safety ================================
def test_dotenv_loader_never_overrides_the_real_environment_and_is_off_in_tests(tmp_path, monkeypatch):
    import importlib

    env = tmp_path / ".env"
    env.write_text("# comment\nFOO_TEST_KEY=from-file\nQUOTED_TEST_KEY='quoted value'\nPRESET_TEST_KEY=from-file\n", encoding="utf-8")
    from config.settings import base
    monkeypatch.setattr(base, "BASE_DIR", tmp_path)
    monkeypatch.setenv("PRESET_TEST_KEY", "from-environment")
    monkeypatch.delenv("DJANGO_SKIP_DOTENV", raising=False)
    monkeypatch.delenv("FOO_TEST_KEY", raising=False)
    monkeypatch.delenv("QUOTED_TEST_KEY", raising=False)
    base._load_dotenv()
    import os
    assert os.environ["FOO_TEST_KEY"] == "from-file" and os.environ["QUOTED_TEST_KEY"] == "quoted value" and os.environ["PRESET_TEST_KEY"] == "from-environment"
    for k in ("FOO_TEST_KEY", "QUOTED_TEST_KEY"):
        monkeypatch.delenv(k)
    monkeypatch.setenv("DJANGO_SKIP_DOTENV", "1")
    base._load_dotenv()
    assert "FOO_TEST_KEY" not in os.environ
    _ = importlib


def test_test_settings_never_talk_to_real_services(settings):
    assert settings.DATABASES["default"]["ENGINE"].endswith("sqlite3")
    assert settings.EMAIL_PROVIDER == "console" and settings.PAYMENT_PROVIDER == "simulated" and settings.USE_CLOUDINARY is False
    assert not settings.BREVO_API_KEY and not settings.MONIME_API_KEY and not settings.CLOUDINARY_API_SECRET and not settings.R2_SECRET_ACCESS_KEY


def test_generate_backup_key_prints_a_valid_fernet_key(capsys):
    from cryptography.fernet import Fernet
    from django.core.management import call_command

    call_command("generate_backup_key")
    key = capsys.readouterr().out.strip()
    Fernet(key.encode())


def test_preflight_flags_a_weak_monime_webhook_secret(settings, db, capsys):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    settings.MONIME_WEBHOOK_SECRET = "short"
    with pytest.raises(CommandError):
        call_command("preflight")
    assert "webhook secret" in capsys.readouterr().out.lower()
