"""Upload scanning.

Layers (uploads are images only; see uploads.CleanImageField):
1. Built-in checks that are always on: the EICAR test signature and script/PHP markers hidden inside "images" (polyglot files).
2. Re-encoding of every accepted image from its decoded pixels, which removes anything hidden in the file (always on).
3. ClamAV through the clamd INSTREAM protocol when UPLOAD_SCANNER = "clamav" (CLAMAV_HOST/CLAMAV_PORT or CLAMAV_SOCKET).
   Production accepts UPLOAD_SCANNER = "clamav" (preferred) or "builtin" (layers 1 and 2 only; use it where no clamd daemon is
   available, for example on Render without a Docker service). Unreachable ClamAV FAILS CLOSED, see UPLOAD_SCAN_FAIL_CLOSED.
"""
import logging
import socket
import struct

from django.conf import settings

log = logging.getLogger(__name__)

EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
MARKERS = (b"<?php", b"<script", b"<%@", b"#!/bin/")
CHUNK = 64 * 1024


class ScanRejected(Exception):
    """The file is infected or suspicious."""


class ScannerUnavailable(Exception):
    """The configured scanner could not be reached."""


def builtin_check(data: bytes):
    if EICAR in data:
        raise ScanRejected("EICAR-Test-Signature")
    head = data[:2_000_000].lower()
    for m in MARKERS:
        if m in head:
            raise ScanRejected(f"embedded-code:{m.decode(errors='ignore')}")


def clamd_scan(data: bytes):
    """Stream the bytes to clamd. Raises ScanRejected on FOUND and ScannerUnavailable on any connection problem."""
    sock_path = getattr(settings, "CLAMAV_SOCKET", "")
    try:
        if sock_path:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(15)
            s.connect(sock_path)
        else:
            s = socket.create_connection((settings.CLAMAV_HOST, int(settings.CLAMAV_PORT)), timeout=15)
        with s:
            s.sendall(b"zINSTREAM\0")
            for i in range(0, len(data), CHUNK):
                chunk = data[i:i + CHUNK]
                s.sendall(struct.pack(">I", len(chunk)) + chunk)
            s.sendall(struct.pack(">I", 0))
            reply = b""
            while not reply.endswith(b"\0") and len(reply) < 4096:
                part = s.recv(1024)
                if not part:
                    break
                reply += part
    except OSError as e:
        raise ScannerUnavailable(type(e).__name__) from e
    text = reply.strip(b"\0").decode(errors="ignore")
    if text.endswith("FOUND"):
        raise ScanRejected(text.split(":", 1)[-1].replace("FOUND", "").strip())
    if not text.endswith("OK"):
        raise ScannerUnavailable(f"unexpected reply: {text[:60]}")


def ping() -> bool:
    """True if clamd answers PING (used by health checks and preflight)."""
    try:
        sock_path = getattr(settings, "CLAMAV_SOCKET", "")
        if sock_path:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect(sock_path)
        else:
            s = socket.create_connection((settings.CLAMAV_HOST, int(settings.CLAMAV_PORT)), timeout=5)
        with s:
            s.sendall(b"zPING\0")
            return s.recv(64).strip(b"\0") == b"PONG"
    except OSError:
        return False


def scan_upload(data: bytes, name: str = ""):
    """Raise ScanRejected or ScannerUnavailable (the latter only when failing closed)."""
    builtin_check(data)
    if getattr(settings, "UPLOAD_SCANNER", "off") != "clamav":
        return
    try:
        clamd_scan(data)
    except ScannerUnavailable as e:
        log.error("Upload scanner unavailable (%s)", e)
        if getattr(settings, "UPLOAD_SCAN_FAIL_CLOSED", True):
            raise
