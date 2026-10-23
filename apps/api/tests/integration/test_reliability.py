"""Failure paths and concurrency: optional dependencies degrade, they never fail a request."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from contextforge.main import create_app
from tests.integration.conftest import (
    Api,
    World,
    bootstrap_owner,
    login,
    make_settings,
    optimize_body,
    reset,
)
from tests.unit.engine.fixtures import coding_trace, support_thread

pytestmark = pytest.mark.integration


@pytest.fixture
async def app_without_redis(database: str, tmp_path: Path, mock_url: str) -> AsyncIterator[FastAPI]:
    """Redis configured but unreachable (port 9 refuses connections)."""
    settings = make_settings(database, tmp_path, mock_url, redis_url="redis://127.0.0.1:9/0")
    await reset(make_settings(database, tmp_path, mock_url), mock_url)
    await bootstrap_owner(settings)
    application = create_app(settings)
    async with LifespanManager(application, startup_timeout=60, shutdown_timeout=30):
        yield application


async def test_redis_down_still_optimizes(app_without_redis: FastAPI, mock_url: str) -> None:
    client = await login(app_without_redis)
    try:
        api = Api(client, app_without_redis, mock_url)
        key = (await api.ok("POST", "/api/v1/keys", {"name": "k"}))["key"]
        for _ in range(2):
            resp = await api.v1(
                key, "/v1/context/optimize", optimize_body(coding_trace(), max_input_tokens=1500)
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["stats"]["budget_met"]
            assert resp.headers["x-contextforge-cache"] == "MISS"
        async with api.anonymous() as c:
            ready = await c.get("/readyz")
        assert ready.status_code == 200 and ready.json()["status"] == "degraded"
        assert ready.json()["checks"]["redis"]["ok"] is False
        metrics = (await client.get("/metrics")).text
        assert 'contextforge_dependency_errors_total{dependency="redis"' in metrics
    finally:
        await client.aclose()


async def test_llm_summarizer_down_falls_back(api: Api, world: World) -> None:
    api.app.state.container.settings.llm_summarizer_url = "http://127.0.0.1:9/v1"
    try:
        resp = await api.v1(
            world.key,
            "/v1/context/optimize",
            optimize_body(support_thread(), max_input_tokens=260, summarizer="llm"),
        )
    finally:
        api.app.state.container.settings.llm_summarizer_url = f"{api.mock_url}/v1"
    body = resp.json()
    assert resp.status_code == 200 and body["summary"]
    w = next(w for w in body["warnings"] if w["code"] == "llm_summarizer_failed")
    assert "ConnectError" in w["details"]["reason"]


async def test_llm_summarizer_unconfigured_is_reported(api: Api, world: World) -> None:
    api.app.state.container.settings.llm_summarizer_url = None
    try:
        resp = await api.v1(
            world.key,
            "/v1/context/summarize",
            {"model": "gpt-4o", "messages": support_thread(), "summarizer": "llm"},
        )
    finally:
        api.app.state.container.settings.llm_summarizer_url = f"{api.mock_url}/v1"
    body = resp.json()
    assert body["summarizer"] == "extractive"
    assert body["warnings"][0]["code"] == "llm_summarizer_failed"


async def test_llm_summarizer_used_in_optimize(api: Api, world: World) -> None:
    body = (
        await api.v1(
            world.key,
            "/v1/context/optimize",
            optimize_body(support_thread(), max_input_tokens=260, summarizer="llm"),
        )
    ).json()
    assert body["summary"] and "Goals:" in body["summary"]
    compress = next(t for t in body["trace"] if t["stage"] == "compress")
    assert any("summary (llm)" in n for n in compress["notes"])


async def test_concurrent_optimizations_all_recorded(api: Api, world: World) -> None:
    bodies = [
        optimize_body(support_thread(5 + i), max_input_tokens=400 + 10 * i) for i in range(30)
    ]
    resps = await asyncio.gather(*(api.v1(world.key, "/v1/context/optimize", b) for b in bodies))
    assert [r.status_code for r in resps] == [200] * 30
    ids = {r.json()["run_id"] for r in resps}
    assert len(ids) == 30
    ov = await api.ok("GET", "/api/v1/analytics/overview?days=1")
    assert ov["runs"] == 30
