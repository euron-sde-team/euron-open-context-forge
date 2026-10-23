"""Application factory."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from contextforge import __version__
from contextforge.audit.router import router as audit_router
from contextforge.auth.router import router as auth_router
from contextforge.benchmark_runs.router import router as benchmarks_router
from contextforge.context.router import router as context_router
from contextforge.core.config import Settings, get_settings
from contextforge.core.container import Container
from contextforge.core.errors import install_error_handlers
from contextforge.core.logs import configure_logging
from contextforge.core.middleware import RequestContextMiddleware
from contextforge.core.tracing import configure_tracing
from contextforge.engine.tokenizers import warm_up
from contextforge.gateway.router import router as gateway_router
from contextforge.jobs.router import router as jobs_router
from contextforge.keys.router import router as keys_router
from contextforge.playground.router import router as playground_router
from contextforge.profiles.router import router as profiles_router
from contextforge.runs.router import router as runs_router
from contextforge.system.router import router as system_router
from contextforge.upstreams.router import router as upstreams_router
from contextforge.users.router import router as users_router

DESCRIPTION = """
Self-hosted context optimization engine. Send the messages, retrieved documents and tool
output you are about to give an LLM; get back the smallest context that still carries every
task-critical fact, with real before and after token counts, warnings and a per-stage trace.

* `/v1/context/*`: optimize, count tokens, summarize, rank, background jobs. Authenticate
  with a service key (`Authorization: Bearer cfk_...`).
* `/v1/chat/completions`: OpenAI-compatible proxy that optimizes, then forwards upstream
  (any OpenAI-compatible API, TokenShield or SmartRouter).
* `/api/v1/*`: the dashboard API (session token from `POST /api/v1/auth/login`).
"""


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    configure_tracing(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container or Container.build(settings)
        await asyncio.to_thread(warm_up)
        try:
            yield
        finally:
            if container is None:
                await app.state.container.close()

    app = FastAPI(
        title="Euron Open ContextForge",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        separate_input_output_schemas=False,
    )
    install_error_handlers(app)
    for router in (
        context_router,
        gateway_router,
        auth_router,
        users_router,
        keys_router,
        profiles_router,
        upstreams_router,
        runs_router,
        jobs_router,
        benchmarks_router,
        playground_router,
        audit_router,
        system_router,
    ):
        app.include_router(router)

    app.add_middleware(GZipMiddleware, minimum_size=2048)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "authorization",
            "content-type",
            "x-contextforge-csrf",
            "x-request-id",
            "x-contextforge-upstream",
            "x-contextforge-max-input-tokens",
            "x-contextforge-strategy",
            "x-contextforge-profile",
            "x-contextforge-optimize",
        ],
        expose_headers=[
            "x-request-id",
            "x-contextforge-run-id",
            "x-contextforge-cache",
            "x-contextforge-original-tokens",
            "x-contextforge-optimized-tokens",
            "x-contextforge-reduction-percent",
            "retry-after",
        ],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware)
    return app
