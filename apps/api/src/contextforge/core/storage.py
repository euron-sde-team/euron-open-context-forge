"""Object storage for report exports: local disk or S3 (Floci locally)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Protocol


class ObjectStorage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def download_url(self, key: str, filename: str, ttl_s: int = 300) -> str | None:
        """A direct URL when the backend supports one; None means stream through the API."""
        ...


class LocalStorage:
    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError("object key escapes the storage root")
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def download_url(self, key: str, filename: str, ttl_s: int = 300) -> str | None:
        return None


class S3Storage:
    def __init__(self, client: Any, bucket: str, presign_client: Any | None = None) -> None:
        self._s3 = client
        # Presigned URLs must carry the host the browser can reach (S3_PUBLIC_ENDPOINT),
        # which differs from the in-network endpoint under Compose.
        self._presign = presign_client or client
        self._bucket = bucket

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._s3.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ServerSideEncryption="aws:kms",
        )

    async def get(self, key: str) -> bytes:
        resp = await asyncio.to_thread(self._s3.get_object, Bucket=self._bucket, Key=key)
        return bytes(resp["Body"].read())

    async def download_url(self, key: str, filename: str, ttl_s: int = 300) -> str | None:
        url = await asyncio.to_thread(
            self._presign.generate_presigned_url,
            "get_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{filename}"',
            },
            ExpiresIn=ttl_s,
        )
        return str(url)
