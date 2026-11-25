import io
import socket
import struct
import tarfile
import threading

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.backups import service
from apps.backups.models import BackupRecord
from apps.backups.storage import get_storage
from apps.core import scanning

from .conftest import client_for
from .test_phase13_backups import KEY, local  # noqa: F401  (fixture)


def png(extra=b"", name="a.png"):
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue() + extra, content_type="image/png")


class FakeClamd:
    """A minimal clamd: speaks the INSTREAM protocol and records what it received."""

    def __init__(self, verdict=b"stream: OK\0"):
        self.verdict, self.received, self.first = verdict, b"", b""
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        with conn:
            buf = b""
            while len(buf) < 10:
                buf += conn.recv(10 - len(buf))
            self.first = buf
            while True:
                hdr = b""
                while len(hdr) < 4:
                    hdr += conn.recv(4 - len(hdr))
                n = struct.unpack(">I", hdr)[0]
                if n == 0:
                    break
                data = b""
                while len(data) < n:
                    data += conn.recv(n - len(data))
                self.received += data
            conn.sendall(self.verdict)

    def close(self):
        self.sock.close()


# ---------------- upload scanning ----------------
def test_builtin_checks_catch_the_eicar_signature_and_embedded_code():
    for bad in (scanning.EICAR, b"GIF89a<?php system($_GET['x']); ?>", b"\x89PNG<script>alert(1)</script>"):
        with pytest.raises(scanning.ScanRejected):
            scanning.builtin_check(b"\x89PNG\r\n" + bad)
    scanning.builtin_check(png().read())  # a clean image passes


def test_clamd_protocol_clean_infected_and_unreachable(settings):
    data = png().read()
    srv = FakeClamd()
    settings.UPLOAD_SCANNER, settings.CLAMAV_HOST, settings.CLAMAV_PORT, settings.CLAMAV_SOCKET = "clamav", "127.0.0.1", srv.port, ""
    scanning.scan_upload(data)
    assert srv.first == b"zINSTREAM\0" and srv.received == data  # exactly the file, length-prefixed chunks, terminated
    srv.close()
    bad = FakeClamd(b"stream: Win.Test.EICAR_HDB-1 FOUND\0")
    settings.CLAMAV_PORT = bad.port
    with pytest.raises(scanning.ScanRejected, match="EICAR"):
        scanning.scan_upload(data)
    bad.close()
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    dead = s.getsockname()[1]
    s.close()
    settings.CLAMAV_PORT = dead
    settings.UPLOAD_SCAN_FAIL_CLOSED = True
    with pytest.raises(scanning.ScannerUnavailable):
        scanning.scan_upload(data)
    settings.UPLOAD_SCAN_FAIL_CLOSED = False  # fail-open is an explicit, non-default choice
    scanning.scan_upload(data)


def test_large_files_are_streamed_in_chunks(settings):
    big = b"\x89PNG" + b"A" * 300_000
    srv = FakeClamd()
    settings.UPLOAD_SCANNER, settings.CLAMAV_PORT = "clamav", srv.port
    scanning.scan_upload(big)
    assert srv.received == big
    srv.close()


def test_uploads_through_the_api_are_scanned(world, settings):
    from apps.catalog.models import Category, Product

    cat = Category.unscoped.create(restaurant=world["a"], name="Mains", slug="mains")
    p = Product.unscoped.create(restaurant=world["a"], category=cat, name="Rice", slug="rice", base_price=5)
    c = client_for(world["admin_a"], "alpha")
    url = f"/api/v1/catalog/products/{p.pk}/image/"
    assert c.post(url, {"image": png()}, format="multipart").status_code == 200
    r = c.post(url, {"image": png(scanning.EICAR)}, format="multipart")
    assert r.status_code == 400 and "security scan" in str(r.json())
    assert c.post(url, {"image": png(b"<?php evil();")}, format="multipart").status_code == 400
    settings.UPLOAD_SCANNER, settings.CLAMAV_PORT, settings.UPLOAD_SCAN_FAIL_CLOSED = "clamav", 1, True
    r = c.post(url, {"image": png()}, format="multipart")
    assert r.status_code == 400 and "temporarily unavailable" in str(r.json())  # fails closed
    cust = client_for(world["cust_a"], "alpha")
    assert cust.post("/api/v1/customers/me/avatar/", {"image": png(scanning.EICAR)}, format="multipart").status_code == 400


def test_production_refuses_to_start_without_the_scanner():
    import subprocess
    import sys

    env_ok = {"PLATFORM_DOMAIN": "example.com", "REDIS_URL": "redis://x", "EMAIL_PROVIDER": "brevo", "BREVO_API_KEY": "k", "BREVO_SENDER_EMAIL": "a@b.c", "PAYMENT_PROVIDER": "monime",
              "MONIME_API_KEY": "k", "MONIME_BASE_URL": "https://x", "MONIME_WEBHOOK_SECRET": "s", "DJANGO_SECRET_KEY": "x" * 60, "DATABASE_URL": "sqlite://:memory:"}
    import os
    base = {**os.environ, **env_ok, "DJANGO_SETTINGS_MODULE": "config.settings.prod", "DJANGO_SKIP_DOTENV": "1"}
    out = subprocess.run([sys.executable, "-c", "import django;django.setup()"], env=base, capture_output=True, text=True)
    assert out.returncode != 0 and "UPLOAD_SCANNER" in out.stderr
    out = subprocess.run([sys.executable, "-c", "import django;django.setup()"], env={**base, "UPLOAD_SCANNER": "clamav"}, capture_output=True, text=True)
    assert "UPLOAD_SCANNER" not in out.stderr


# ---------------- media backups ----------------
@pytest.fixture
def media(settings, tmp_path):
    root = tmp_path / "media"
    (root / "products").mkdir(parents=True)
    (root / "products" / "a.png").write_bytes(b"png-one")
    (root / "logo.png").write_bytes(b"logo-bytes")
    settings.MEDIA_ROOT = str(root)
    return root


def take():
    return service.run_backup(BackupRecord.objects.create(kind="manual"))


def test_backup_includes_an_encrypted_media_archive(world, local, media):  # noqa: F811
    rec = take()
    assert rec.status == "succeeded" and rec.media_files == 2 and rec.media_object_key.startswith("media/") and rec.media_size_bytes > 0
    blob = get_storage().get(rec.media_object_key)
    assert b"png-one" not in blob and b"logo-bytes" not in blob  # ciphertext
    assert service.verify_backup(rec).verify_ok is True


def test_media_tamper_and_missing_file_count_fail_verification(world, local, media):  # noqa: F811
    rec = take()
    get_storage().put(rec.media_object_key, b"tampered")
    bad = service.verify_backup(rec)
    assert bad.verify_ok is False and "Media checksum mismatch" in bad.verify_error


def test_media_restore_never_overwrites_and_recreates_missing_files(world, local, media, tmp_path):  # noqa: F811
    rec = take()
    dest = tmp_path / "restored"
    assert service.restore_media(rec, dest) == 2
    assert (dest / "products" / "a.png").read_bytes() == b"png-one" and (dest / "logo.png").read_bytes() == b"logo-bytes"
    (dest / "logo.png").write_bytes(b"newer")
    assert service.restore_media(rec, dest) == 0 and (dest / "logo.png").read_bytes() == b"newer"  # existing files are kept


def test_media_restore_refuses_path_traversal(world, local, media, tmp_path, settings):  # noqa: F811
    rec = take()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("../escape.txt")
        data = b"owned"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    from apps.backups.service import _fernet
    import hashlib
    blob = _fernet().encrypt(buf.getvalue())
    get_storage().put(rec.media_object_key, blob)
    rec.media_sha256 = hashlib.sha256(blob).hexdigest()
    with pytest.raises(service.BackupError, match="unsafe"):
        service.restore_media(rec, tmp_path / "dest")
    assert not (tmp_path / "escape.txt").exists()


def test_no_media_is_reported_not_failed(world, local, settings, tmp_path):  # noqa: F811
    settings.MEDIA_ROOT = str(tmp_path / "empty")
    rec = take()
    assert rec.status == "succeeded" and rec.media_object_key == "" and "No uploaded files" in rec.media_note


def test_oversized_media_never_discards_the_database_backup(world, local, media, settings):  # noqa: F811
    settings.BACKUP_MEDIA_MAX_MB = 0
    rec = take()
    assert rec.status == "succeeded" and rec.media_object_key == "" and "Media not backed up" in rec.media_note


def test_prune_removes_media_archives_too(world, local, media, settings):  # noqa: F811
    from datetime import timedelta

    from django.utils import timezone

    settings.BACKUP_KEEP_MIN, settings.BACKUP_RETAIN_DAYS = 0, 1
    rec = take()
    BackupRecord.objects.filter(pk=rec.pk).update(created_at=timezone.now() - timedelta(days=5))
    assert service.prune() == 1
    with pytest.raises(FileNotFoundError):
        get_storage().get(rec.media_object_key)


def test_api_reports_media_details(world, local, media):  # noqa: F811
    r = client_for(world["platform"]).post("/api/v1/system/backups/")
    assert r.status_code == 201 and r.json()["data"]["media_files"] == 2 and r.json()["data"]["media_size_bytes"] > 0
    assert "media_object_key" not in r.json()["data"]
    _ = KEY


def test_health_reports_scanner_and_mfa_state(world, local, settings):  # noqa: F811
    from apps.backups.health import system_health

    by = {c["name"]: c for c in system_health()["checks"]}
    assert by["Upload scanning"]["status"] == "warning" and by["Two-factor authentication"]["status"] == "warning"
    srv = FakeClamd()
    srv2 = None
    settings.UPLOAD_SCANNER, settings.CLAMAV_PORT, settings.MFA_ENFORCEMENT = "clamav", srv.port, True
    # the fake answers PING with a verdict-less reply, so use a dedicated responder
    srv.close()

    class Ping(FakeClamd):
        def serve(self):
            conn, _ = self.sock.accept()
            with conn:
                conn.recv(16)
                conn.sendall(b"PONG\0")

    srv2 = Ping()
    settings.CLAMAV_PORT = srv2.port
    by = {c["name"]: c for c in system_health()["checks"]}
    assert by["Upload scanning"]["status"] == "ok" and by["Two-factor authentication"]["status"] == "warning"  # the platform admin has not enrolled
    srv2.close()
    by = {c["name"]: c for c in system_health()["checks"]}
    assert by["Upload scanning"]["status"] == "critical"  # unreachable and failing closed


def test_preflight_lists_the_new_security_checks(db, capsys):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("preflight")
    out = capsys.readouterr().out
    assert "Two-factor authentication is enforced" in out and "Upload scanning uses ClamAV" in out
