"""The in-process KV backend and the config cache (no Redis needed)."""

from __future__ import annotations

import asyncio

import pytest

from contextforge.core.cache import ConfigCache
from contextforge.core.kv import MemoryKV, create_kv


async def test_memory_kv_get_set_expiry_and_lru() -> None:
    kv = MemoryKV(max_entries=2)
    await kv.set("a", b"1", ttl_s=60)
    await kv.set("b", b"2", ttl_s=60)
    assert await kv.get("a") == b"1"
    await kv.set("c", b"3", ttl_s=60)  # evicts b (a was used more recently)
    assert await kv.get("b") is None and await kv.get("a") == b"1"
    await kv.set("d", b"4", ttl_s=-1)
    assert await kv.get("d") is None
    await kv.ping()
    await kv.close()
    assert await kv.get("a") is None


async def test_memory_kv_counters_and_rate_window() -> None:
    kv = MemoryKV()
    assert await kv.incr("v") == 1 and await kv.incr("v") == 2
    assert await kv.get("v") == b"2"
    decisions = [await kv.hit("k", 2) for _ in range(3)]
    assert [d.allowed for d in decisions] == [True, True, False]
    assert decisions[2].retry_after_s >= 1


def test_create_kv_picks_backend() -> None:
    assert create_kv("").backend == "memory"
    assert create_kv("redis://localhost:1/0").backend == "redis"


async def test_config_cache_single_flight_and_invalidation() -> None:
    kv = MemoryKV()
    cache = ConfigCache(kv, ttl_s=60, check_interval_s=0)
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return calls

    results = await asyncio.gather(*(cache.get("x", loader) for _ in range(5)))
    assert results == [1] * 5 and calls == 1
    await cache.invalidate()
    assert await cache.get("x", loader) == 2
    assert cache.version == "1"


async def test_config_cache_sees_other_instances_writes() -> None:
    kv = MemoryKV()
    a, b = ConfigCache(kv, check_interval_s=0), ConfigCache(kv, check_interval_s=0)
    n = 0

    async def loader() -> int:
        nonlocal n
        n += 1
        return n

    assert await b.get("k", loader) == 1
    await a.invalidate()
    assert await b.get("k", loader) == 2


async def test_config_cache_ttl_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = ConfigCache(MemoryKV(), ttl_s=0.01, check_interval_s=60)
    values = iter([1, 2])

    async def loader() -> int:
        return next(values)

    assert await cache.get("k", loader) == 1
    await asyncio.sleep(0.02)
    assert await cache.get("k", loader) == 2
