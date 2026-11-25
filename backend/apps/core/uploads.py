"""Shared upload helpers: randomised storage names and real-image validation."""
import uuid

from django.utils.deconstruct import deconstructible
from rest_framework import serializers

ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG", "WEBP"}  # SVG excluded on purpose (script injection)


@deconstructible
class RandomUploadPath:
    """upload_to callable producing `<prefix>/<uuid>.<ext>`: user-controlled filenames never reach storage."""

    def __init__(self, prefix):
        self.prefix = prefix

    def __call__(self, instance, filename):
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "img"
        return f"{self.prefix}/{uuid.uuid4().hex}.{ext[:5]}"


def random_upload_path(prefix):
    return RandomUploadPath(prefix)


MAX_DIMENSION = 4096


class CleanImageField(serializers.ImageField):
    """Image upload that is checked, scanned and then RE-ENCODED.

    1. size and real format (Pillow decodes the file; SVG and anything else is refused);
    2. security scan of the original bytes (built-in checks and, when configured, ClamAV);
    3. the picture is decoded and saved again from its pixels: hidden payloads, polyglot tails, scripts in metadata and EXIF
       (including GPS position) do not survive, orientation is applied, and giant images are shrunk to 4096 px.
    """

    def __init__(self, max_bytes, **kw):
        self.max_bytes = max_bytes
        super().__init__(**kw)

    def to_internal_value(self, data):
        f = super().to_internal_value(data)
        if f.size > self.max_bytes:
            raise serializers.ValidationError(f"Image must be {self.max_bytes // (1024 * 1024)} MB or smaller.")
        img = getattr(f, "image", None)
        if img is None or img.format not in ALLOWED_IMAGE_FORMATS:
            raise serializers.ValidationError("Image must be a PNG, JPEG or WebP file.")
        from .scanning import ScannerUnavailable, ScanRejected, scan_upload

        f.seek(0)
        raw = f.read()
        try:
            scan_upload(raw, getattr(f, "name", ""))
        except ScanRejected:
            raise serializers.ValidationError("This file was rejected by the security scan.")
        except ScannerUnavailable:
            raise serializers.ValidationError("Uploads are temporarily unavailable. Please try again later.")
        return self._reencode(raw, img.format, getattr(f, "name", "image"))

    @staticmethod
    def _reencode(raw: bytes, fmt: str, name: str):
        import io

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image, ImageOps

        try:
            with Image.open(io.BytesIO(raw)) as im:
                im.load()
                im = ImageOps.exif_transpose(im)
                im.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
                out = io.BytesIO()
                if fmt == "JPEG":
                    im.convert("RGB").save(out, "JPEG", quality=88, optimize=True)
                elif fmt == "WEBP":
                    im.save(out, "WEBP", quality=85)
                else:
                    im.save(out, "PNG", optimize=True)
        except Exception:  # noqa: BLE001
            raise serializers.ValidationError("This image could not be processed.")
        ext = {"JPEG": "jpg", "WEBP": "webp", "PNG": "png"}[fmt]
        stem = name.rsplit("/", 1)[-1].rsplit(".", 1)[0] or "image"
        return SimpleUploadedFile(f"{stem}.{ext}", out.getvalue(), content_type={"jpg": "image/jpeg", "webp": "image/webp", "png": "image/png"}[ext])


def image_field(max_bytes):
    """DRF image field: size and format limits, security scan, and re-encoding (see CleanImageField)."""
    return CleanImageField(max_bytes)
