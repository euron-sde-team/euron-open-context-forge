"""Process-wide services, built once in the app lifespan and shared by every request.

Holding them in one object (on ``app.state``) instead of module globals keeps the app
factory re-entrant and lets tests build an isolated container per app.
"""

from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime

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
    engine_slots: asyncio.Semaphore
    engine_pool: ThreadPoolExecutor
    llm_http: httpx.Client
    # key id -> when this process last wrote its last_used_at (bounded by the key count).
    key_touched: dict[uuid.UUID, datetime] = field(default_factory=dict)

    @classmethod
    def build(cls, settings: Settings) -> Container:
        kv = create_kv(settings.redis_url, settings.memory_cache_max_bytes)
        sealer: KeySealer = (
            KmsSealer(aws_client(settings, "kms"), settings.kms_key_id)
            if settings.key_mode == "kms"
            else LocalSealer(settings.local_master_key)
        )
        storage: ObjectStorage = (
            S3Storage(aws_client(settings, "s3"), settings.payloads_bucket)
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
            engine_slots=asyncio.Semaphore(settings.engine_concurrency),
            engine_pool=ThreadPoolExecutor(
                max_workers=settings.engine_concurrency, thread_name_prefix="engine"
            ),
            # One pooled client for the optional LLM summarizer (called from engine threads).
            llm_http=httpx.Client(timeout=httpx.Timeout(settings.llm_timeout_s, connect=5.0)),
        )

    async def close(self) -> None:
        await self.http.aclose()
        self.llm_http.close()
        self.engine_pool.shutdown(wait=False, cancel_futures=True)
        await self.kv.close()
        await self.db.dispose()
