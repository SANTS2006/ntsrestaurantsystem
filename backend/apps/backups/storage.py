"""Where backup archives live. Cloudflare R2 (S3 API) in production; a local folder only when explicitly allowed."""
from pathlib import Path

from django.conf import settings


class StorageError(Exception):
    pass


def r2_configured() -> bool:
    return all([settings.R2_BUCKET, settings.R2_ACCESS_KEY_ID, settings.R2_SECRET_ACCESS_KEY, (settings.R2_ACCOUNT_ID or settings.R2_ENDPOINT_URL)])


class R2Storage:
    name = "r2"

    def __init__(self):
        import boto3

        self.bucket = settings.R2_BUCKET
        self.client = boto3.client(
            "s3", endpoint_url=settings.R2_ENDPOINT_URL or f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.R2_ACCESS_KEY_ID, aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY, region_name="auto")

    def put(self, key, data: bytes):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def get(self, key) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def check(self):
        self.client.head_bucket(Bucket=self.bucket)

    def list(self, prefix="backups/"):
        out = []
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            out += [o["Key"] for o in page.get("Contents", [])]
        return sorted(out)


class LocalStorage:
    name = "local"

    def __init__(self):
        self.root = Path(settings.BACKUP_LOCAL_DIR)

    def _path(self, key):
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise StorageError("Invalid object key.")
        return p

    def put(self, key, data: bytes):
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key):
        self._path(key).unlink(missing_ok=True)

    def list(self, prefix="backups/"):
        return sorted(p.relative_to(self.root).as_posix() for p in (self.root / prefix).rglob("*") if p.is_file())

    def check(self):
        self.root.mkdir(parents=True, exist_ok=True)
        probe = self.root / ".write-test"
        probe.write_bytes(b"ok")
        probe.unlink()


def get_storage():
    if r2_configured():
        return R2Storage()
    if settings.BACKUP_ALLOW_LOCAL:
        return LocalStorage()
    raise StorageError("No backup storage is configured. Set the R2_* variables (local backups are for development only).")
