"""Object storage behind one tiny interface.

Rows in image/job tables store KEYS ("uploads/x.png", "jobs/<id>/enhanced.png"),
never absolute paths. LocalStorage (dev default) resolves keys against
settings.storage_dir; S3Storage talks to any S3-compatible bucket (R2 in
production, zero egress) and is selected when all four r2_* settings are set.
"""

import mimetypes
from functools import lru_cache
from pathlib import Path

from app.core.config import settings


class LocalStorage:
    def __init__(self, base: Path):
        self.base = base

    def _path(self, key: str) -> Path:
        p = Path(key)
        # legacy rows (pre-storage-layer) stored paths like "storage/uploads/x.png"
        return p if p.exists() else self.base / key

    def put(self, key: str, data: bytes) -> None:
        path = self.base / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3Storage:
    def __init__(self, account_id: str, key_id: str, secret: str, bucket: str):
        import boto3  # deferred: dev installs never touch it at import time

        self.client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=key_id,
            aws_secret_access_key=secret,
            region_name="auto",
        )
        self.bucket = bucket

    def put(self, key: str, data: bytes) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=media_type_for(key),
        )

    def get(self, key: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.client.exceptions.NoSuchKey:
            # same contract as LocalStorage.get on a missing file
            raise FileNotFoundError(key) from None

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


def media_type_for(key: str) -> str:
    return mimetypes.guess_type(key)[0] or "application/octet-stream"


@lru_cache(maxsize=1)
def get_storage() -> LocalStorage | S3Storage:
    if all(
        (
            settings.r2_account_id,
            settings.r2_access_key_id,
            settings.r2_secret_access_key,
            settings.r2_bucket,
        )
    ):
        return S3Storage(
            settings.r2_account_id,
            settings.r2_access_key_id,
            settings.r2_secret_access_key,
            settings.r2_bucket,
        )
    return LocalStorage(Path(settings.storage_dir))
