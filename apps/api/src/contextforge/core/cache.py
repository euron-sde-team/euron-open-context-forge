"""In-process TTL cache with cluster-wide invalidation through a version stamp.

Hot paths (service key lookup, profiles, upstreams) read configuration on every request.
Each process keeps a short-lived copy; any admin write bumps ``cf:cfg:version`` in the KV
store, and every process compares its stamp at most once per ``check_interval`` and drops
its copy when the stamp moved. With the memory backend the stamp is per process, which is
exact for a single replica.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from redis.exceptions import RedisError

from contextforge.core.kv import KV

T = TypeVar("T")
VERSION_KEY = "cf:cfg:version"
log = logging.getLogger("contextforge.cache")


class ConfigCache:
    def __init__(self, kv: KV, *, ttl_s: float = 5.0, check_interval_s: float = 1.0) -> None:
        self._kv = kv
        self._ttl = ttl_s
        self._check_interval = check_interval_s
        self._entries: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._version: bytes | None = None
        self._checked_at = 0.0

    @property
    def version(self) -> str:
        return (self._version or b"0").decode()

    async def _sync_version(self) -> None:
        now = time.monotonic()
        if now - self._checked_at < self._check_interval:
            return
        self._checked_at = now
        try:
            version = await self._kv.get(VERSION_KEY)
        except (RedisError, OSError):
            return  # without the stamp, fall back to TTL expiry only
        if version != self._version:
            self._entries.clear()
            self._version = version

    async def get(self, key: str, loader: Callable[[], Awaitable[T]]) -> T:
        await self._sync_version()
        hit = self._entries.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]  # type: ignore[no-any-return]
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            hit = self._entries.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]  # type: ignore[no-any-return]
            value = await loader()
            self._entries[key] = (time.monotonic() + self._ttl, value)
            return value

    async def invalidate(self) -> None:
        """Called after every configuration write."""
        self._entries.clear()
        try:
            self._version = str(await self._kv.incr(VERSION_KEY)).encode()
            self._checked_at = time.monotonic()
        except (RedisError, OSError):
            log.warning("could not bump config version; other instances refresh on TTL")
