"""Abuse and race cases: hostile input, forged headers, parallel requests, lost leases.

Each test pins one production-readiness guarantee: bounded work per request, no 500s on
odd but valid JSON, credentials that cannot be redirected, and state that stays correct
under concurrency.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, update

from contextforge.audit.models import AuditLog
from contextforge.core.storage import ObjectNotFoundError
from contextforge.jobs import service as jobs
from contextforge.jobs.models import Job
from contextforge.users.models import User
from tests.integration.conftest import OWNER, Api, World, login, optimize_body
from tests.unit.engine.fixtures import coding_trace

pytestmark = pytest.mark.integration


def _tool_turns(tool_output: str) -> list[dict[str, Any]]:
    """A tool result old enough to be optimized, followed by recent turns."""
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": "You are a coding agent."},
        {"role": "user", "content": "Inspect the payload."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": tool_output},
    ]
    for i in range(3):
        msgs.append({"role": "assistant", "content": f"Step {i} done."})
        msgs.append({"role": "user", "content": f"Continue with step {i + 1}."})
    return msgs


# ── Bounded work and odd input ───────────────────────────────────────────────────────


async def test_deeply_nested_tool_json_is_not_a_500(api: Api, world: World) -> None:
    deep = "[" * 5000 + "]" * 5000
    resp = await api.v1(
        world.key, "/v1/context/optimize", optimize_body(_tool_turns(deep), max_input_tokens=4000)
    )
    assert resp.status_code == 200, resp.text


async def test_lone_surrogate_is_not_a_500(api: Api, world: World) -> None:
    # Valid JSON (an escaped lone surrogate) that is not valid UTF-8 once decoded.
    raw = (
        b'{"model": "gpt-4o", "messages": [{"role": "user", '
        b'"content": "broken \\ud800 text, then a question?"}]}'
    )
    async with api.anonymous() as c:
        resp = await c.post(
            "/v1/context/optimize",
            content=raw,
            headers={"authorization": f"Bearer {world.key}", "content-type": "application/json"},
        )
    assert resp.status_code == 422, resp.text
    assert "surrogate" in resp.text


async def test_engine_saturation_answers_503_with_retry_after(api: Api, world: World) -> None:
    container = api.app.state.container
    slots, timeout = container.engine_slots, container.settings.engine_queue_timeout_s
    container.engine_slots = asyncio.Semaphore(0)  # every slot is taken
    container.settings.engine_queue_timeout_s = 0.05
    try:
        resp = await api.v1(world.key, "/v1/context/optimize", optimize_body(coding_trace(2)))
    finally:
        container.engine_slots, container.settings.engine_queue_timeout_s = slots, timeout
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "engine_busy"
    assert resp.headers["retry-after"] == "2"


async def test_engine_slot_is_released_after_each_run(api: Api, world: World) -> None:
    container = api.app.state.container
    free = container.engine_slots._value
    for _ in range(3):
        resp = await api.v1(world.key, "/v1/context/optimize", optimize_body(coding_trace(2)))
        assert resp.status_code == 200
    assert container.engine_slots._value == free


async def test_rank_handles_many_passages_quickly(api: Api, world: World) -> None:
    docs = [
        {"id": f"d{i}", "text": f"Passage {i} is about topic {i % 50} and value {i}."}
        for i in range(3000)
    ]
    loop = asyncio.get_running_loop()
    started = loop.time()
    resp = await api.v1(
        world.key, "/v1/context/rank", {"query": "topic 7", "passages": docs, "top_k": 5}
    )
    assert resp.status_code == 200, resp.text
    assert loop.time() - started < 15


# ── Credentials and headers ──────────────────────────────────────────────────────────


async def test_malformed_key_prefix_never_reaches_cache_or_db(api: Api) -> None:
    resp = await api.v1(
        "cfk_ZZZZZZZZZZZZ_secret",
        "/v1/context/count-tokens",
        {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_api_key"
    assert not any("ZZZZ" in k for k in api.app.state.container.config_cache._entries)


async def test_upstream_header_is_validated(api: Api, world: World) -> None:
    resp = await api.v1(
        world.key,
        "/v1/chat/completions",
        {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers={"x-contextforge-upstream": "../../etc/passwd"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "unknown_upstream"


async def test_moving_an_upstream_to_another_host_needs_its_key_again(
    api: Api, world: World
) -> None:
    up = world.upstreams["plain"]
    resp = await api.client.patch(
        f"/api/v1/upstreams/{up}", json={"base_url": "https://attacker.example.test/v1"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "api_key_required"
    # Same host, new path: the stored key may stay.
    await api.ok("PATCH", f"/api/v1/upstreams/{up}", {"base_url": api.mock_url + "/v1/"})
    # New host with a new key: allowed, and the move is audited.
    await api.ok(
        "PATCH",
        f"/api/v1/upstreams/{up}",
        {"base_url": "https://other.example.test/v1", "api_key": "new-upstream-secret-0000"},
    )
    audit = await api.ok("GET", "/api/v1/audit?action=upstream.updated")
    assert any(e["details"].get("to_host") == "https://other.example.test" for e in audit["items"])


async def test_forwarded_for_cannot_dodge_the_login_throttle(api: Api) -> None:
    async with api.anonymous() as c:
        codes = []
        for i in range(22):
            r = await c.post(
                "/api/v1/auth/login",
                json={"email": "nobody@example.test", "password": "wrong-password"},
                headers={"x-forwarded-for": f"203.0.113.{i}"},
            )
            codes.append(r.status_code)
    assert codes[-1] == 429


async def test_parallel_wrong_passwords_still_lock_the_account(api: Api) -> None:
    async with api.anonymous() as c:
        await asyncio.gather(
            *(
                c.post("/api/v1/auth/login", json={"email": OWNER["email"], "password": "nope"})
                for _ in range(8)
            )
        )
        locked = await c.post("/api/v1/auth/login", json=OWNER)
    assert locked.json()["error"]["code"] == "account_locked"
    async with api.app.state.container.db.sessionmaker() as s:
        failures = await s.scalar(
            select(func.count()).where(AuditLog.action == "auth.login_failed")
        )
    assert failures == 8


async def test_logout_ends_the_session_server_side(api: Api) -> None:
    client = await login(api.app)
    try:
        assert (await client.get("/api/v1/auth/me")).status_code == 200
        resp = await client.post("/api/v1/auth/logout")
        assert resp.status_code == 200
        again = await client.get("/api/v1/auth/me")
        assert again.status_code == 401
        assert again.json()["error"]["code"] == "session_expired"
    finally:
        await client.aclose()
    # Other sessions of the same user keep working.
    assert (await api.client.get("/api/v1/auth/me")).status_code == 200
    actions = {e["action"] for e in (await api.ok("GET", "/api/v1/audit"))["items"]}
    assert "auth.logout" in actions


async def test_login_response_is_not_cached(api: Api) -> None:
    async with api.anonymous() as c:
        resp = await c.post("/api/v1/auth/login", json=OWNER)
    assert resp.headers["cache-control"] == "no-store"


# ── Races ────────────────────────────────────────────────────────────────────────────


async def test_two_owners_demoting_each_other_keep_an_owner(api: Api) -> None:
    other = {"email": "second-owner@example.test", "password": "Second-Owner-123"}
    created = await api.ok(
        "POST", "/api/v1/users", {"name": "Second", "role": "owner", **other}, status=201
    )
    me = await api.ok("GET", "/api/v1/auth/me")
    second = await login(api.app, other)
    try:
        results = await asyncio.gather(
            api.client.patch(f"/api/v1/users/{created['id']}", json={"role": "viewer"}),
            second.patch(f"/api/v1/users/{me['id']}", json={"role": "viewer"}),
        )
    finally:
        await second.aclose()
    assert sorted(r.status_code for r in results)[0] == 200
    async with api.app.state.container.db.sessionmaker() as s:
        owners = await s.scalar(
            select(func.count()).where(User.role == "owner", User.disabled.is_(False))
        )
    assert owners == 1


async def test_parallel_benchmark_requests_queue_one(api: Api) -> None:
    results = await asyncio.gather(
        *(api.client.post("/api/v1/benchmarks", json={"runs_per_case": 1}) for _ in range(4))
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [202, 409, 409, 409]


async def test_worker_that_lost_its_lease_cannot_overwrite(api: Api, world: World) -> None:
    await api.v1(world.key, "/v1/context/jobs", optimize_body(coding_trace(2)))
    container = api.app.state.container
    container.settings.job_lease_s = -1
    try:
        stale = await jobs.claim(container)
        current = await jobs.claim(container)
    finally:
        container.settings.job_lease_s = 300
    assert stale is not None and current is not None and current.attempts == 2
    await jobs.process(container, stale)  # finishes late: its writes are fenced off
    async with container.db.sessionmaker() as s:
        row = await s.get(Job, stale.id)
        assert row is not None and row.status == "running" and row.result_key is None
    await jobs.process(container, current)
    async with container.db.sessionmaker() as s:
        row = await s.get(Job, current.id)
        assert row is not None and row.status == "succeeded"


async def test_job_that_keeps_killing_workers_is_failed(api: Api, world: World) -> None:
    await api.v1(world.key, "/v1/context/jobs", optimize_body(coding_trace(2)))
    container = api.app.state.container
    async with container.db.sessionmaker() as s:
        await s.execute(
            update(Job).values(
                status="running",
                attempts=jobs.MAX_ATTEMPTS,
                lease_until=datetime.now(UTC) - timedelta(seconds=5),
            )
        )
        await s.commit()
    assert await jobs.claim(container) is None
    job = (await api.ok("GET", "/api/v1/jobs"))[0]
    assert job["status"] == "failed"
    assert job["error"]["code"] == "job_abandoned"


async def test_rollups_group_unknown_models(api: Api, world: World) -> None:
    for model in ("gpt-4o-2024-08-06", "acme-llm-7", "acme-llm-8"):
        body = {**optimize_body(coding_trace(1)), "model": model}
        assert (await api.v1(world.key, "/v1/context/optimize", body)).status_code == 200
    overview = await api.ok("GET", "/api/v1/analytics/overview?days=1")
    keys = {b["key"]: b["runs"] for b in overview["by_model"]}
    assert keys == {"gpt-4o": 1, "other": 2}


async def test_streamed_proxy_survives_a_compressing_upstream(api: Api, world: World) -> None:
    # httpx asks upstreams for gzip by default; the relay must decode before it re-labels.
    resp = await api.v1(
        world.key,
        "/v1/chat/completions",
        {"model": "gpt-4o", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
        headers={"x-contextforge-upstream": "plain"},
    )
    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers
    assert resp.text.startswith("data:"), resp.content[:40]


# ── Second review: leaks, limits and references ──────────────────────────────────────


async def test_racing_user_creates_conflict_without_leaking_hashes(
    api: Api, caplog: pytest.LogCaptureFixture
) -> None:
    body = {
        "email": "race@example.test",
        "name": "Race",
        "role": "viewer",
        "password": "Race-Pass-12345",
    }
    results = await asyncio.gather(*(api.client.post("/api/v1/users", json=body) for _ in range(4)))
    codes = sorted(r.status_code for r in results)
    assert codes[0] == 201 and set(codes[1:]) <= {409}
    assert "argon2" not in caplog.text


async def test_signed_out_session_survives_cache_eviction(api: Api) -> None:
    client = await login(api.app)
    try:
        await client.post("/api/v1/auth/logout")
        kv = api.app.state.container.kv
        for i in range(3000):  # far more than the in-process cache holds
            await kv.set(f"filler:{i}", b"x" * 100, 60)
        if hasattr(kv, "redis"):
            await kv.redis.flushdb()
        assert (await client.get("/api/v1/auth/me")).status_code == 401
    finally:
        await client.aclose()


async def test_chunked_bodies_obey_the_body_limit(api: Api, world: World) -> None:
    settings = api.app.state.container.settings
    settings.max_body_bytes = 1000

    async def chunks() -> AsyncIterator[bytes]:
        yield b'{"model": "gpt-4o", "messages": [{"role": "user", "content": "'
        for _ in range(50):
            yield b"x" * 500
        yield b'"}]}'

    try:
        async with api.anonymous() as c:
            for path, headers in (
                ("/v1/context/optimize", {"authorization": f"Bearer {world.key}"}),
                ("/v1/chat/completions", {"authorization": f"Bearer {world.key}"}),
            ):
                resp = await c.post(
                    path, content=chunks(), headers={**headers, "content-type": "application/json"}
                )
                assert resp.status_code == 413, (path, resp.text)
                assert resp.json()["error"]["code"] == "payload_too_large"
        resp = await api.client.post(
            "/api/v1/playground/optimize",
            content=chunks(),
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 413
    finally:
        settings.max_body_bytes = 32_000_000


async def test_proxy_validation_errors_are_422_not_500(api: Api, world: World) -> None:
    for body in (
        {"model": "gpt-4o", "messages": []},
        {"model": "m" * 300, "messages": [{"role": "user", "content": "hi"}]},
    ):
        resp = await api.v1(world.key, "/v1/chat/completions", body)
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "validation_error"


async def test_expired_run_content_is_410(
    api: Api, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = api.app.state.container
    container.settings.store_content = True
    try:
        resp = await api.v1(world.key, "/v1/context/optimize", optimize_body(coding_trace(1)))
        run_id = resp.json()["run_id"]
    finally:
        container.settings.store_content = False
    assert (await api.client.get(f"/api/v1/runs/{run_id}/content")).status_code == 200

    async def gone(key: str) -> bytes:
        raise ObjectNotFoundError(key)

    monkeypatch.setattr(container.storage, "get", gone)
    resp = await api.client.get(f"/api/v1/runs/{run_id}/content")
    assert resp.status_code == 410
    assert resp.json()["error"]["code"] == "content_expired"


async def test_every_cpu_endpoint_respects_engine_slots(api: Api, world: World) -> None:
    container = api.app.state.container
    slots, timeout = container.engine_slots, container.settings.engine_queue_timeout_s
    container.engine_slots = asyncio.Semaphore(0)
    container.settings.engine_queue_timeout_s = 0.05
    try:
        for path, body in (
            ("/v1/context/count-tokens", {"model": "gpt-4o", "text": "hello"}),
            ("/v1/context/summarize", {"model": "gpt-4o", "messages": coding_trace(1)}),
            (
                "/v1/context/rank",
                {"query": "q", "passages": [{"id": "a", "text": "some text"}]},
            ),
        ):
            resp = await api.v1(world.key, path, body)
            assert resp.status_code == 503, (path, resp.text)
    finally:
        container.engine_slots, container.settings.engine_queue_timeout_s = slots, timeout


async def test_key_defaults_must_exist_and_stay_referenced(api: Api, world: World) -> None:
    resp = await api.client.post("/api/v1/keys", json={"name": "x", "default_profile": "nope"})
    assert resp.json()["error"]["code"] == "unknown_profile"
    resp = await api.client.patch(
        f"/api/v1/keys/{world.key_id}", json={"default_upstream": "missing"}
    )
    assert resp.json()["error"]["code"] == "unknown_upstream"

    profile = {
        "name": "incident",
        "description": "Incidents",
        "weights": {"history": 0.5, "tool": 0.5, "documents": 0, "summary": 0},
        "relevance": 0.5,
        "recency": 0.5,
        "importance": 0,
    }
    await api.ok("POST", "/api/v1/profiles", profile, status=201)
    await api.ok("PATCH", f"/api/v1/keys/{world.key_id}", {"default_profile": "incident"})
    resp = await api.client.delete("/api/v1/profiles/incident")
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "profile_in_use"
    resp = await api.client.delete(f"/api/v1/upstreams/{world.upstreams['plain']}")
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "upstream_in_use"


async def test_upstreams_cannot_target_instance_metadata(api: Api) -> None:
    for url in ("http://169.254.169.254/latest", "http://[fd00:ec2::254]/v1"):
        resp = await api.client.post(
            "/api/v1/upstreams", json={"name": "meta", "kind": "openai", "base_url": url}
        )
        assert resp.status_code == 422, url
