"""Integration harness: the real app in-process against real Postgres (and Redis, Floci S3
and KMS when the option matrix selects them), with the mock LLM served over real HTTP from a
background thread.

    make test-integration      (starts Postgres and Redis containers if needed)
    make test-matrix           (reruns everything under every backend combination)

Safety: the suite truncates every table, so it refuses any database whose name does not
contain "test", and any non-local host unless ALLOW_REMOTE_TEST_DB=true.
"""

from __future__ import annotations

import asyncio
import os
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
import uvicorn
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from contextforge.core.config import Settings
from contextforge.main import create_app

TEST_DB = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://contextforge:contextforge@localhost:4342/contextforge_test",
)
# TEST_CACHE=memory runs the whole suite with no Redis at all (acceptance criterion 1).
TEST_CACHE = os.environ.get("TEST_CACHE", "redis")
TEST_REDIS = os.environ.get("TEST_REDIS_URL", "redis://localhost:4379/15")
OWNER = {"email": "owner@example.test", "password": "Owner-Pass-123"}
TABLES = (
    "run_rollups_hourly, optimization_runs, jobs, benchmark_runs, audit_log, api_keys, "
    "upstreams, workload_profiles, revoked_sessions, users"
)


def _guard(url: str) -> None:
    parsed = urlparse(url.replace("+asyncpg", ""))
    if "test" not in (parsed.path or ""):
        raise RuntimeError(
            f"refusing to run against {parsed.path!r}: database name must contain 'test'"
        )
    if (
        parsed.hostname not in ("localhost", "127.0.0.1", "postgres")
        and os.environ.get("ALLOW_REMOTE_TEST_DB") != "true"
    ):
        raise RuntimeError("refusing a non-local test database (set ALLOW_REMOTE_TEST_DB=true)")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def mock_url() -> Iterator[str]:
    port = _free_port()
    config = uvicorn.Config("mockllm.app:app", host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="session")
async def database() -> AsyncIterator[str]:
    _guard(TEST_DB)
    admin_url = TEST_DB.rsplit("/", 1)[0] + "/postgres"
    name = TEST_DB.rsplit("/", 1)[1]
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    await engine.dispose()
    from contextforge.migrations.runner import upgrade

    await asyncio.to_thread(upgrade, TEST_DB)
    yield TEST_DB


def make_settings(database: str, tmp_path: Path, mock_url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "database_url": database,
        "redis_url": TEST_REDIS if TEST_CACHE == "redis" else "",
        "session_secret": "test-only-session-secret-with-32-plus-bytes",
        "api_key_pepper": "test-only-api-key-pepper-with-32-plus-bytes",
        "local_master_key": "test-only-master-key-with-32-plus-bytes-ok",
        "local_storage_dir": str(tmp_path / "payloads"),
        "upstream_timeout_s": 2,
        "llm_summarizer_url": f"{mock_url}/v1",
        "llm_timeout_s": 2,
        "tokenizer_aliases": {"chat-small": "gpt-4o-mini"},
        # The option matrix (make test-matrix) reruns the suite against Floci KMS and S3.
        "key_mode": os.environ.get("TEST_KEY_MODE", "local"),
        "storage": os.environ.get("TEST_STORAGE", "local"),
        "aws_endpoint_url": os.environ.get("TEST_AWS_ENDPOINT"),
        "s3_force_path_style": True,
        "kms_key_id": os.environ.get("TEST_KMS_KEY_ID", "alias/contextforge-local"),
        "payloads_bucket": os.environ.get("TEST_PAYLOADS_BUCKET", "contextforge-local-payloads"),
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def settings(database: str, tmp_path: Path, mock_url: str) -> Settings:
    return make_settings(database, tmp_path, mock_url)


async def reset(settings: Settings, mock_url: str) -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    await engine.dispose()
    if settings.redis_url:
        from redis.asyncio import Redis

        redis = Redis.from_url(settings.redis_url)
        await redis.flushdb()
        await redis.aclose()
    async with httpx.AsyncClient() as client:
        await client.post(f"{mock_url}/stats/reset")


async def bootstrap_owner(settings: Settings) -> None:
    from contextforge.core.db import Database
    from contextforge.core.security import hash_password
    from contextforge.users.models import User

    db = Database(settings.database_url, pool_size=1, max_overflow=0)
    async with db.sessionmaker() as session:
        session.add(
            User(
                email=OWNER["email"],
                name="Owner",
                role="owner",
                password_hash=hash_password(OWNER["password"]),
            )
        )
        await session.commit()
    await db.dispose()


@dataclass
class Api:
    """A signed-in admin client plus helpers for common setup."""

    client: httpx.AsyncClient
    app: FastAPI
    mock_url: str

    async def mock_stats(self) -> dict[str, Any]:
        async with httpx.AsyncClient() as c:
            data: dict[str, Any] = (await c.get(f"{self.mock_url}/stats")).json()
            return data

    async def ok(self, method: str, path: str, json: Any = None, status: int | None = None) -> Any:
        resp = await self.client.request(method, path, json=json)
        expected = status or (201 if method == "POST" and resp.status_code == 201 else 200)
        assert resp.status_code == expected, f"{method} {path}: {resp.status_code} {resp.text}"
        return resp.json() if resp.content else None

    async def v1(
        self, key: str | None, path: str, json: Any, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        h = dict(headers or {})
        if key:
            h["authorization"] = f"Bearer {key}"
        # A service call must not ride on the dashboard session.
        async with self.anonymous() as client:
            return await client.post(path, json=json, headers=h)

    def anonymous(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://testserver", timeout=30
        )


@pytest.fixture
async def app(settings: Settings, mock_url: str) -> AsyncIterator[FastAPI]:
    await reset(settings, mock_url)
    await bootstrap_owner(settings)
    application = create_app(settings)
    async with LifespanManager(application, startup_timeout=60, shutdown_timeout=30):
        yield application


async def login(app: FastAPI, creds: dict[str, str] = OWNER) -> httpx.AsyncClient:
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=30
    )
    resp = await client.post("/api/v1/auth/login", json=creds)
    assert resp.status_code == 200, resp.text
    client.headers["authorization"] = f"Bearer {resp.json()['session_token']}"
    return client


@pytest.fixture
async def api(app: FastAPI, mock_url: str) -> AsyncIterator[Api]:
    client = await login(app)
    try:
        yield Api(client, app, mock_url)
    finally:
        await client.aclose()


@dataclass
class World:
    """Service keys and upstreams pointing at the mock LLM."""

    key: str
    key_id: str
    upstreams: dict[str, str]


@pytest.fixture
async def world(api: Api) -> World:
    upstreams = {}
    for name, kind, path in (
        ("plain", "openai", "/v1"),
        ("shield", "tokenshield", "/tokenshield/v1"),
        ("router", "smartrouter", "/smartrouter/v1"),
    ):
        up = await api.ok(
            "POST",
            "/api/v1/upstreams",
            {
                "name": name,
                "kind": kind,
                "base_url": api.mock_url + path,
                "api_key": f"upstream-secret-{name}-0000",
                "max_input_tokens": 4000,
            },
        )
        upstreams[name] = up["id"]
    key = await api.ok("POST", "/api/v1/keys", {"name": "tests", "default_upstream": "plain"})
    return World(key["key"], key["id"], upstreams)


def optimize_body(messages: list[dict[str, Any]], **options: Any) -> dict[str, Any]:
    return {"model": "gpt-4o", "messages": messages, "options": options}
