"""AC14: background jobs with payloads in object storage, claimed safely by workers."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from contextforge.jobs import service as jobs
from contextforge.jobs.models import Job
from tests.integration.conftest import Api, World, optimize_body
from tests.unit.engine.fixtures import coding_trace

pytestmark = pytest.mark.integration


async def test_ac14_job_lifecycle(api: Api, world: World) -> None:
    body = optimize_body(coding_trace(10), max_input_tokens=1500)
    resp = await api.v1(world.key, "/v1/context/jobs", body)
    assert resp.status_code == 202
    job_id = resp.json()["id"]
    async with api.anonymous() as c:
        status = (
            await c.get(resp.json()["poll"], headers={"authorization": f"Bearer {world.key}"})
        ).json()
    assert status["status"] == "queued" and status["result"] is None
    container = api.app.state.container
    async with container.db.sessionmaker() as s:
        row = await s.scalar(select(Job).where(Job.id == job_id))
    assert row is not None and row.payload_key.startswith(f"jobs/{job_id}/")
    # The row holds the object key only; the payload itself is in object storage.
    assert len(await container.storage.get(row.payload_key)) == row.payload_bytes
    assert await jobs.run_once(container) is True
    async with api.anonymous() as c:
        done = (
            await c.get(
                f"/v1/context/jobs/{job_id}", headers={"authorization": f"Bearer {world.key}"}
            )
        ).json()
    assert done["status"] == "succeeded" and done["run_id"]
    assert done["result"]["stats"]["budget_met"] is True
    run = await api.ok("GET", f"/api/v1/runs/{done['run_id']}")
    assert run["source"] == "job"
    listed = await api.ok("GET", "/api/v1/jobs")
    assert listed[0]["id"] == job_id and listed[0]["result"] is None


async def test_jobs_are_scoped_to_their_key(api: Api, world: World) -> None:
    job_id = (await api.v1(world.key, "/v1/context/jobs", optimize_body(coding_trace(2)))).json()[
        "id"
    ]
    other = (await api.ok("POST", "/api/v1/keys", {"name": "other"}))["key"]
    async with api.anonymous() as c:
        resp = await c.get(
            f"/v1/context/jobs/{job_id}", headers={"authorization": f"Bearer {other}"}
        )
    assert resp.status_code == 404


async def test_failed_job_reports_why(api: Api, world: World) -> None:
    body = {
        "model": "unknown-model-x",
        "messages": coding_trace(2),
        "options": {"allow_estimate": False},
    }
    job_id = (await api.v1(world.key, "/v1/context/jobs", body)).json()["id"]
    await jobs.run_once(api.app.state.container)
    async with api.anonymous() as c:
        done = (
            await c.get(
                f"/v1/context/jobs/{job_id}", headers={"authorization": f"Bearer {world.key}"}
            )
        ).json()
    assert done["status"] == "failed" and done["error"]["code"] == "unsupported_tokenizer"


async def test_concurrent_workers_never_double_claim(api: Api, world: World) -> None:
    for _ in range(6):
        await api.v1(
            world.key, "/v1/context/jobs", optimize_body(coding_trace(2), max_input_tokens=900)
        )
    container = api.app.state.container
    claimed = await asyncio.gather(*(jobs.claim(container) for _ in range(10)))
    ids = [j.id for j in claimed if j is not None]
    assert len(ids) == 6 and len(set(ids)) == 6
    await asyncio.gather(*(jobs.process(container, j) for j in claimed if j is not None))
    async with container.db.sessionmaker() as s:
        statuses = (await s.scalars(select(Job.status))).all()
    assert set(statuses) == {"succeeded"}


async def test_expired_lease_is_reclaimed(api: Api, world: World) -> None:
    await api.v1(world.key, "/v1/context/jobs", optimize_body(coding_trace(2)))
    container = api.app.state.container
    container.settings.job_lease_s = -1  # the first worker "crashes" with an already expired lease
    try:
        first = await jobs.claim(container)
        again = await jobs.claim(container)
    finally:
        container.settings.job_lease_s = 300
    assert first is not None and again is not None and first.id == again.id
    assert again.attempts == 2


async def test_worker_tick_processes_jobs_and_benchmarks(api: Api, world: World) -> None:
    from contextforge.worker import tick

    container = api.app.state.container
    assert await tick(container) is False
    await api.v1(
        world.key, "/v1/context/jobs", optimize_body(coding_trace(2), max_input_tokens=900)
    )
    assert await tick(container) is True
    assert (await api.ok("GET", "/api/v1/jobs"))[0]["status"] == "succeeded"


async def test_key_update_changes_defaults(api: Api, world: World) -> None:
    out = await api.ok(
        "PATCH",
        f"/api/v1/keys/{world.key_id}",
        {"name": "renamed", "default_profile": "support", "rpm_limit": 50},
    )
    assert out["name"] == "renamed" and out["default_profile"] == "support"
    body = (await api.v1(world.key, "/v1/context/optimize", optimize_body(coding_trace(2)))).json()
    assert body["profile"] == "support"
    assert (
        await api.client.patch(
            "/api/v1/keys/00000000-0000-0000-0000-000000000000", json={"name": "x"}
        )
    ).status_code == 404


async def test_expired_job_result_is_gone_not_an_error(api: Api, world: World) -> None:
    job_id = (await api.v1(world.key, "/v1/context/jobs", optimize_body(coding_trace(2)))).json()[
        "id"
    ]
    container = api.app.state.container
    await jobs.run_once(container)
    async with container.db.sessionmaker() as s:
        row = await s.get(Job, job_id)
        assert row is not None
        row.result_key = f"jobs/{job_id}/expired.json"  # what the bucket lifecycle leaves behind
        await s.commit()
    async with api.anonymous() as c:
        resp = await c.get(
            f"/v1/context/jobs/{job_id}", headers={"authorization": f"Bearer {world.key}"}
        )
    assert resp.status_code == 410 and resp.json()["error"]["code"] == "job_result_expired"
