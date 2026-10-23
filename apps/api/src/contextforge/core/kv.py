"""A small key-value interface with two backends: Redis, or process memory.

ContextForge must run with no Redis at all, so everything that would use Redis (the result
cache, per-key rate limits, the config version stamp) goes through :class:`KV`. With
``REDIS_URL`` set, state is shared by every replica; without it, each process keeps its
own, which is exact for a single replica and documented as such.

A Redis outage never stops optimization: callers treat cache and limiter errors as a miss
or a pass and count them in ``contextforge_dependency_errors_total``.
"""

from __future__ import annotations

import math
import time
from collections import OrderedDict
from typing import Protocol

from redis.asyncio import Redis

from contextforge.limits.limiter import LimitDecision, Limiter


class KV(Protocol):
    backend: str

    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes, ttl_s: int) -> None: ...
    async def incr(self, key: str) -> int: ...
    async def hit(self, name: str, limit: int, amount: int = 1) -> LimitDecision: ...
    async def ping(self) -> None: ...
    async def close(self) -> None: ...


class RedisKV:
    backend = "redis"

    def __init__(self, url: str) -> None:
        self.redis = Redis.from_url(
            url,
            decode_responses=False,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
            health_check_interval=15,
            retry_on_timeout=False,
        )
        self._limiter = Limiter(self.redis)

    async def get(self, key: str) -> bytes | None:
        value = await self.redis.get(key)
        if value is None:
            return None
        return value if isinstance(value, bytes) else str(value).encode()

    async def set(self, key: str, value: bytes, ttl_s: int) -> None:
        await self.redis.set(key, value, ex=ttl_s)

    async def incr(self, key: str) -> int:
        return int(await self.redis.incr(key))

    async def hit(self, name: str, limit: int, amount: int = 1) -> LimitDecision:
        return await self._limiter.hit(name, limit, amount)

    async def ping(self) -> None:
        await self.redis.ping()

    async def close(self) -> None:
        await self.redis.aclose()


_FOREVER_S = 10 * 365 * 24 * 3600


class MemoryKV:
    """Bounded LRU with expiry, plus fixed-window rate counters. One process only."""

    backend = "memory"

    def __init__(self, max_entries: int = 2048) -> None:
        self._data: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self._windows: dict[str, tuple[int, int]] = {}
        self._max = max_entries

    async def get(self, key: str) -> bytes | None:
        hit = self._data.get(key)
        if hit is None:
            return None
        if hit[0] < time.monotonic():
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return hit[1]

    async def set(self, key: str, value: bytes, ttl_s: int) -> None:
        self._data[key] = (time.monotonic() + ttl_s, value)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    async def incr(self, key: str) -> int:
        current = await self.get(key)
        value = int(current or b"0") + 1
        await self.set(key, str(value).encode(), _FOREVER_S)
        return value

    async def hit(self, name: str, limit: int, amount: int = 1) -> LimitDecision:
        now = time.time()
        window = int(now // Limiter.WINDOW_S)
        current_window, count = self._windows.get(name, (window, 0))
        if current_window != window:
            count = 0
        if count + amount > limit:
            retry = math.ceil(Limiter.WINDOW_S - (now % Limiter.WINDOW_S))
            return LimitDecision(False, max(1, retry), count)
        self._windows[name] = (window, count + amount)
        return LimitDecision(True, 0, count + amount)

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        self._data.clear()


def create_kv(redis_url: str) -> KV:
    return RedisKV(redis_url) if redis_url else MemoryKV()
