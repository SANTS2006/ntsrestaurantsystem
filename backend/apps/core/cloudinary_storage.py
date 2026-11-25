"""Django file storage backed by Cloudinary (signed uploads through the REST API; no extra dependency).

Only images are uploaded in this product (every upload passes through `image_field`: real image decoding, size and
format limits, malware scan). Names are random (`<folder>/<uuid>.<ext>`), so overwriting never happens.
"""
import hashlib
import io
import time

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import File
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

API = "https://api.cloudinary.com/v1_1"
CDN = "https://res.cloudinary.com"


def configured() -> bool:
    return bool(settings.CLOUDINARY_CLOUD_NAME and settings.CLOUDINARY_API_KEY and settings.CLOUDINARY_API_SECRET)


def _sign(params: dict) -> str:
    """Cloudinary signature: SHA-1 of the sorted `k=v` pairs joined by `&`, followed by the API secret."""
    payload = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v not in (None, ""))
    return hashlib.sha1((payload + settings.CLOUDINARY_API_SECRET).encode()).hexdigest()


def _split(name: str):
    name = name.lstrip("/")
    if "." in name.rsplit("/", 1)[-1]:
        return name.rsplit(".", 1)[0], name.rsplit(".", 1)[1]
    return name, ""


@deconstructible
class CloudinaryStorage(Storage):
    def __init__(self):
        if not configured():
            raise ImproperlyConfigured("Cloudinary is not configured (CLOUDINARY_CLOUD_NAME / API_KEY / API_SECRET).")

    def _post(self, action, params, files=None):
        params = {**params, "timestamp": int(time.time())}
        data = {**{k: v for k, v in params.items() if v not in (None, "")}, "api_key": settings.CLOUDINARY_API_KEY, "signature": _sign(params)}
        try:
            r = requests.post(f"{API}/{settings.CLOUDINARY_CLOUD_NAME}/image/{action}", data=data, files=files, timeout=30)
        except requests.RequestException as exc:
            raise OSError("Cloudinary is unreachable.") from exc
        if r.status_code != 200:
            raise OSError(f"Cloudinary rejected the request (HTTP {r.status_code}).")
        return r.json()

    def _save(self, name, content):
        public_id, ext = _split(name)
        content.seek(0)
        data = content.read()
        res = self._post("upload", {"public_id": public_id, "overwrite": "false", "unique_filename": "false", "invalidate": "false"}, files={"file": (f"{public_id.rsplit('/', 1)[-1]}.{ext or 'img'}", io.BytesIO(data))})
        got = res.get("public_id", public_id)
        fmt = res.get("format") or ext
        return f"{got}.{fmt}" if fmt else got

    def url(self, name):
        return f"{CDN}/{settings.CLOUDINARY_CLOUD_NAME}/image/upload/q_auto/{name.lstrip('/')}"

    def delete(self, name):
        public_id, _ = _split(name)
        try:
            self._post("destroy", {"public_id": public_id, "invalidate": "true"})
        except OSError:
            pass  # a failed cleanup must never break the request that triggered it

    def exists(self, name):
        return False  # names are random UUIDs: a collision is not a realistic case

    def open(self, name, mode="rb"):
        r = requests.get(self.url(name), timeout=30)
        r.raise_for_status()
        return File(io.BytesIO(r.content), name=name)

    def size(self, name):
        return 0
