"""Rate (RPM, TPM) and concurrency limits in Redis.

Rates use the sliding-window counter algorithm: the previous fixed window's count is
weighted by how much of it still overlaps the sliding window. It needs two integers per
limit, is exact at window boundaries to within a few percent, and runs as one atomic
script so concurrent requests cannot overshoot.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.asyncio.client import Pipeline

_SLIDING = """
local amount = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local window = tonumber(ARGV[3])
local frac = tonumber(ARGV[4])
local cur = tonumber(redis.call('GET', KEYS[1]) or '0')
local prev = tonumber(redis.call('GET', KEYS[2]) or '0')
local weighted = prev * (1 - frac) + cur
if weighted + amount > limit then
  return {0, math.floor(weighted)}
end
redis.call('INCRBY', KEYS[1], amount)
redis.call('EXPIRE', KEYS[1], window * 2)
return {1, math.floor(weighted + amount)}
"""

_ACQUIRE = """
local n = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ARGV[2])
if n > tonumber(ARGV[1]) then
  redis.call('DECR', KEYS[1])
  return 0
end
return 1
"""

_RELEASE = """
local n = redis.call('DECR', KEYS[1])
if n < 0 then redis.call('SET', KEYS[1], 0) end
return 1
"""


@dataclass(frozen=True, slots=True)
class LimitDecision:
    allowed: bool
    retry_after_s: int = 0
    observed: int = 0


class Limiter:
    WINDOW_S = 60

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._sliding = redis.register_script(_SLIDING)
        self._acquire = redis.register_script(_ACQUIRE)
        self._release = redis.register_script(_RELEASE)

    def _keys(self, name: str, now: float) -> tuple[list[str], float, int]:
        window = int(now // self.WINDOW_S)
        frac = (now % self.WINDOW_S) / self.WINDOW_S
        retry = math.ceil(self.WINDOW_S - (now % self.WINDOW_S))
        return [f"cf:rl:{name}:{window}", f"cf:rl:{name}:{window - 1}"], frac, retry

    async def hit(self, name: str, limit: int, amount: int = 1) -> LimitDecision:
        now = time.time()
        keys, frac, retry = self._keys(name, now)
        allowed, observed = await self._sliding(
            keys=keys, args=[amount, limit, self.WINDOW_S, f"{frac:.6f}"]
        )
        return LimitDecision(bool(int(allowed)), 0 if allowed else max(1, retry), int(observed))

    async def correct(self, name: str, delta: int) -> None:
        """Adjust the current window after the real token count is known."""
        if delta == 0:
            return
        keys, _, _ = self._keys(name, time.time())
        await self._redis.incrby(keys[0], delta)

    def correct_in(self, pipe: Pipeline, name: str, delta: int) -> None:
        if delta:
            keys, _, _ = self._keys(name, time.time())
            pipe.incrby(keys[0], delta)

    async def acquire(self, name: str, limit: int, ttl_s: int) -> bool:
        return bool(int(await self._acquire(keys=[f"cf:conc:{name}"], args=[limit, ttl_s])))

    async def release(self, name: str) -> None:
        await self._release(keys=[f"cf:conc:{name}"])
