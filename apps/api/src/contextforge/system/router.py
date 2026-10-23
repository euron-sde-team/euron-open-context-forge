"""Health, readiness, metrics and deployment info."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select, text

from contextforge import __version__
from contextforge.auth.dependencies import Viewer
from contextforge.core.deps import ContainerDep, SessionDep
from contextforge.core.schemas import ApiModel
from contextforge.engine.profiles import BUILTIN_PROFILES
from contextforge.engine.tokenizers import ENCODINGS
from contextforge.keys.models import ApiKey
from contextforge.upstreams.models import Upstream

router = APIRouter(tags=["system"])


@router.get("/healthz", summary="Liveness")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health", summary="Liveness (alias of /healthz)")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


async def _probe(name: str, coro: Awaitable[Any]) -> tuple[str, dict[str, Any]]:
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(coro, timeout=2)
        return name, {"ok": True, "ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as exc:
        return name, {"ok": False, "error": type(exc).__name__}


@router.get("/readyz", summary="Readiness: Postgres reachable (Redis too, when configured)")
async def readyz(container: ContainerDep, response: Response) -> dict[str, Any]:
    async def pg() -> None:
        async with container.db.engine.connect() as conn:
            await conn.execute(text("select 1"))

    probes = [_probe("postgres", pg())]
    if container.kv.backend == "redis":
        probes.append(_probe("redis", container.kv.ping()))
    checks = dict(await asyncio.gather(*probes))
    # Redis is optional: when it is down the service still optimizes, so only Postgres
    # decides readiness. A Redis failure is reported as degraded but stays ready.
    ok = checks["postgres"]["ok"]
    response.status_code = 200 if ok else 503
    degraded = not all(c["ok"] for c in checks.values())
    return {"status": "degraded" if degraded else "ready", "checks": checks}


@router.get("/metrics", summary="Prometheus metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class SystemInfo(ApiModel):
    version: str
    environment: str
    cloud: str
    key_mode: str
    storage: str
    cache_backend: str
    auth_required: bool
    store_content: bool
    llm_summarizer: bool
    tokenizers: list[str]
    tokenizer_aliases: dict[str, str]
    builtin_profiles: list[str]
    upstreams: int
    active_keys: int
    checks: dict[str, Any]


@router.get("/api/v1/system", response_model=SystemInfo, summary="Deployment configuration")
async def system(_: Viewer, session: SessionDep, container: ContainerDep) -> SystemInfo:
    s = container.settings
    upstreams = await session.scalar(select(func.count()).select_from(Upstream))
    keys = await session.scalar(select(func.count()).where(ApiKey.revoked_at.is_(None)))
    checks: dict[str, Any] = {"postgres": {"ok": True}}
    if container.kv.backend == "redis":
        checks.update(dict([await _probe("redis", container.kv.ping())]))
    return SystemInfo(
        version=__version__,
        environment=s.environment,
        cloud=s.cloud,
        key_mode=s.key_mode,
        storage=s.storage,
        cache_backend=container.kv.backend,
        auth_required=s.auth_required,
        store_content=s.store_content,
        llm_summarizer=bool(s.llm_summarizer_url),
        tokenizers=list(ENCODINGS),
        tokenizer_aliases=s.tokenizer_aliases,
        builtin_profiles=list(BUILTIN_PROFILES),
        upstreams=int(upstreams or 0),
        active_keys=int(keys or 0),
        checks=checks,
    )
