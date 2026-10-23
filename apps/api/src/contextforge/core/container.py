"""Process-wide services, built once in the app lifespan and shared by every request.

Holding them in one object (on ``app.state``) instead of module globals keeps the app
factory re-entrant and lets tests build an isolated container per app.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from contextforge.core.aws import aws_client
from contextforge.core.cache import ConfigCache
from contextforge.core.config import Settings
from contextforge.core.db import Database
from contextforge.core.kv import KV, create_kv
from contextforge.core.sealing import KeySealer, KmsSealer, LocalSealer
from contextforge.core.storage import LocalStorage, ObjectStorage, S3Storage
from contextforge.engine.tokenizers import TokenizerRegistry


def build_http_client(timeout_s: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=5.0),
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
        follow_redirects=False,
    )


@dataclass
class Container:
    settings: Settings
    db: Database
    kv: KV
    http: httpx.AsyncClient
    config_cache: ConfigCache
    sealer: KeySealer
    storage: ObjectStorage
    tokenizers: TokenizerRegistry

    @classmethod
    def build(cls, settings: Settings) -> Container:
        kv = create_kv(settings.redis_url)
        sealer: KeySealer = (
            KmsSealer(aws_client(settings, "kms"), settings.kms_key_id)
            if settings.key_mode == "kms"
            else LocalSealer(settings.local_master_key)
        )
        storage: ObjectStorage = (
            S3Storage(
                aws_client(settings, "s3"),
                settings.payloads_bucket,
                aws_client(settings, "s3", public=True),
            )
            if settings.storage == "s3"
            else LocalStorage(settings.local_storage_dir)
        )
        return cls(
            settings=settings,
            db=Database(
                settings.database_url,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
            ),
            kv=kv,
            http=build_http_client(settings.upstream_timeout_s),
            config_cache=ConfigCache(kv),
            sealer=sealer,
            storage=storage,
            tokenizers=TokenizerRegistry(settings.tokenizer_aliases),
        )

    async def close(self) -> None:
        await self.http.aclose()
        await self.kv.close()
        await self.db.dispose()
