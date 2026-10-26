"""Service key authentication and per-key rate limits for /v1.

Lookups go through the config cache (5 s TTL, cluster-wide invalidation), so the hot path
never waits on Postgres; ``last_used_at`` is touched at most once a minute per key.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Request
from redis.exceptions import RedisError
from sqlalchemy import select, update

from contextforge.core.container import Container
from contextforge.core.deps import ContainerDep
from contextforge.core.errors import AuthenticationError, RateLimitedError
from contextforge.core.security import constant_time_equals, hash_key_secret, parse_api_key
from contextforge.keys.models import ApiKey
from contextforge.observability import metrics

log = logging.getLogger("contextforge.keys")
_TOUCH_EVERY = timedelta(minutes=1)


@dataclass(frozen=True, slots=True)
class KeyContext:
    id: uuid.UUID | None
    name: str
    rpm_limit: int
    default_profile: str | None
    default_upstream: str | None


@dataclass(frozen=True, slots=True)
class _KeyRow:
    id: uuid.UUID
    name: str
    secret_hash: str
    rpm_limit: int | None
    default_profile: str | None
    default_upstream: str | None
    expires_at: datetime | None
    revoked: bool
    last_used_at: datetime | None


async def _load(container: Container, prefix: str) -> _KeyRow | None:
    async with container.db.sessionmaker() as session:
        key = await session.scalar(select(ApiKey).where(ApiKey.prefix == prefix))
        if key is None:
            return None
        return _KeyRow(
            key.id,
            key.name,
            key.secret_hash,
            key.rpm_limit,
            key.default_profile,
            key.default_upstream,
            key.expires_at,
            key.revoked_at is not None,
            key.last_used_at,
        )


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.headers.get("x-api-key") or None


async def service_key(request: Request, container: ContainerDep) -> KeyContext:
    settings = container.settings
    raw = _bearer(request)
    if raw is None:
        if not settings.auth_required:
            return KeyContext(None, "anonymous", settings.default_rpm_limit, None, None)
        raise AuthenticationError(
            "Send a ContextForge service key as 'Authorization: Bearer cfk_...'",
            code="missing_api_key",
        )
    parsed = parse_api_key(raw)
    if parsed is None:
        raise AuthenticationError(
            "That is not a ContextForge key (cfk_...)", code="invalid_api_key"
        )
    prefix, secret = parsed
    row = await container.config_cache.get(f"key:{prefix}", lambda: _load(container, prefix))
    now = datetime.now(UTC)
    if row is None or not constant_time_equals(
        row.secret_hash, hash_key_secret(secret, settings.api_key_pepper)
    ):
        raise AuthenticationError("Unknown API key", code="invalid_api_key")
    if row.revoked:
        raise AuthenticationError("This API key was revoked", code="revoked_api_key")
    if row.expires_at and row.expires_at <= now:
        raise AuthenticationError("This API key has expired", code="expired_api_key")
    limit = row.rpm_limit or settings.default_rpm_limit
    try:
        decision = await container.kv.hit(f"key:{row.id}", limit)
    except (RedisError, OSError):
        metrics.DEPENDENCY_ERRORS.labels("redis", "rate_limit").inc()
        decision = None  # rate limits are protective; optimization keeps working
    if decision is not None and not decision.allowed:
        raise RateLimitedError(
            f"Rate limit of {limit} requests per minute reached for this key",
            details={"limit_rpm": limit, "retry_after_s": decision.retry_after_s},
            headers={"retry-after": str(decision.retry_after_s)},
        )
    # The row is cached for a few seconds, so its last_used_at lags; remember this
    # process's own last write too, or every request in that window would write again.
    touched = container.key_touched.get(row.id)
    last = max(filter(None, (row.last_used_at, touched)), default=None)
    if last is None or now - last > _TOUCH_EVERY:
        container.key_touched[row.id] = now
        try:
            async with container.db.sessionmaker() as session:
                await session.execute(
                    update(ApiKey).where(ApiKey.id == row.id).values(last_used_at=now)
                )
                await session.commit()
        except Exception:  # a failed bookkeeping write must not fail the request
            log.warning("could not record key usage", exc_info=True)
    return KeyContext(row.id, row.name, limit, row.default_profile, row.default_upstream)


ServiceKey = Annotated[KeyContext, Depends(service_key)]
