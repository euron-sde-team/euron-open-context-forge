# ADR-0002: Redis is optional, with an in-process fallback

- **Status:** Accepted
- **Date:** 2026-10-24

## Context

ContextForge uses shared state for three things: the result cache (identical requests
answered without rerunning the pipeline), per-key and per-IP rate limits, and the config
version stamp that invalidates every replica's configuration cache. Redis is the natural
home for all three when several replicas run. But a context optimizer is often adopted
as one container next to an application, or as a library, and requiring Redis would make
the smallest deployment heavier than the problem it solves. A Redis outage must also never
stop optimization, which is correct without any of this state.

## Decision

Every use of shared state goes through one small protocol, `KV` (`core/kv.py`), with two
implementations chosen by configuration only:

- `RedisKV` when `REDIS_URL` is set: results with a TTL, rate limits as a sliding-window
  counter in one atomic Lua script, and `INCR` on `cf:cfg:version`.
- `MemoryKV` when `REDIS_URL` is empty: a bounded LRU (2,048 entries) with expiry, and
  fixed-window rate counters, per process.

Callers treat a Redis error as a degraded dependency, never as a request failure: a cache
read error is a miss, a cache write error is skipped, a limiter error lets the request
through, and a failed version check leaves the config cache on its 5 s TTL. Each is counted
in `contextforge_dependency_errors_total`. `/readyz` reports Redis as `degraded` but stays
ready, because only Postgres decides readiness.

## Consequences

**Good**
- The service runs with Postgres alone. The integration suite runs with and without Redis
  (`make test-matrix`, legs `cache=redis` and `cache=memory`), which proves acceptance
  criterion 1.
- A Redis outage costs cache hits and rate limiting, not availability.

**Bad / caveats**
- Without Redis, state is per process: each replica has its own cache and its own rate
  counters (a key's effective limit is multiplied by the replica count), and a revocation
  reaches other replicas only when their 5 s config TTL expires. Exact for one replica,
  documented for more.
- During a Redis outage rate limits are not enforced. This is a deliberate choice for an
  optimizer: spend control belongs to TokenShield, which fails closed.

## Alternatives considered

- **Redis required.** Simpler code, heavier minimum deployment, and an outage would take
  down a service that does not need Redis to be correct.
- **Postgres for counters and cache.** Puts write load for every request on the database
  that holds the audit trail.
- **Fail closed on Redis errors.** Right for a budget gateway, wrong for an optimizer whose
  result is the same with or without the cache.
