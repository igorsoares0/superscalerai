"""Object storage behind one tiny interface.

Rows in image/job tables store KEYS ("uploads/x.png", "jobs/<id>/enhanced.png"),
never absolute paths. LocalStorage (dev default) resolves keys against
settings.storage_dir; S3Storage talks to any S3-compatible bucket (R2 in
production, zero egress) and is selected when all four r2_* settings are set.
"""

import mimetypes
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from app.core.config import settings

# Streaming reads hand the response back in pieces instead of building the
# whole file in memory first — an enhanced PNG at max_image_px is tens of MB,
# and the box is sized for job peaks, not for concurrent downloads.
CHUNK = 256 * 1024


class LocalStorage:
    def __init__(self, base: Path):
        self.base = base

    def _path(self, key: str) -> Path:
        """Resolve a key to a file INSIDE the storage root, or refuse.

        Legacy rows (pre-storage-layer) stored "storage/uploads/x.png" rather
        than "uploads/x.png", so that prefix is stripped explicitly. The old
        version instead used Path(key) as-is whenever it happened to exist,
        which quietly made any key an arbitrary filesystem read — keys are all
        ours today, but this is the one place where a key from somewhere else
        would become a file on disk.
        """
        relative = Path(key)
        if relative.is_absolute():
            raise FileNotFoundError(key)
        parts = relative.parts
        if parts and parts[0] == self.base.name:  # legacy row
            parts = parts[1:]
        base = self.base.resolve()
        path = base.joinpath(*parts).resolve()
        if not path.is_relative_to(base):  # ../.. climbing out
            raise FileNotFoundError(key)
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def stream(self, key: str) -> Iterator[bytes]:
        # Opened here, NOT inside the generator: a generator body doesn't run
        # until the first chunk is pulled, by which point the response has
        # already started and a missing file can no longer become a 404.
        handle = self._path(key).open("rb")

        def chunks() -> Iterator[bytes]:
            with handle:
                while chunk := handle.read(CHUNK):
                    yield chunk

        return chunks()

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
        return self._body(key).read()

    def stream(self, key: str) -> Iterator[bytes]:
        # get_object resolves eagerly, so a missing key raises here rather
        # than mid-response — same contract as LocalStorage.stream.
        return self._body(key).iter_chunks(CHUNK)

    def _body(self, key: str):
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        except self.client.exceptions.NoSuchKey:
            # same contract as LocalStorage on a missing file
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
            settings.r2_secret_access_key.get_secret_value(),
            settings.r2_bucket,
        )
    ):
        return S3Storage(
            settings.r2_account_id,
            settings.r2_access_key_id,
            settings.r2_secret_access_key.get_secret_value(),
            settings.r2_bucket,
        )
    return LocalStorage(Path(settings.storage_dir))
