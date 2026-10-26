"""AC15: runs, rollups and the overview the dashboard shows."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from contextforge.benchmark_runs import service as bench
from tests.integration.conftest import Api, World, login, optimize_body
from tests.unit.engine.fixtures import coding_trace, support_thread

pytestmark = pytest.mark.integration


async def test_runs_list_detail_and_rollups_agree(api: Api, world: World) -> None:
    for msgs, budget in (
        (coding_trace(), 1500),
        (support_thread(), 700),
        (support_thread(4), None),
    ):
        resp = await api.v1(
            world.key, "/v1/context/optimize", optimize_body(msgs, max_input_tokens=budget)
        )
        assert resp.status_code == 200
    page = await api.ok("GET", "/api/v1/runs?limit=2")
    assert len(page["items"]) == 2 and page["next_cursor"]
    rest = await api.ok("GET", f"/api/v1/runs?limit=2&cursor={page['next_cursor']}")
    assert len(rest["items"]) == 1 and rest["next_cursor"] is None
    detail = await api.ok("GET", f"/api/v1/runs/{page['items'][0]['id']}")
    assert detail["trace"] and detail["allocation"] and detail["has_content"] is False
    ov = await api.ok("GET", "/api/v1/analytics/overview?days=7")
    runs = page["items"] + rest["items"]
    assert ov["runs"] == 3
    assert ov["tokens_before"] == sum(r["tokens_before"] for r in runs)
    assert ov["tokens_saved"] == sum(r["tokens_before"] - r["tokens_after"] for r in runs)
    assert ov["fact_retention"] == pytest.approx(
        sum(r["facts_retained"] for r in runs) / sum(r["facts_total"] for r in runs), abs=1e-4
    )
    assert ov["cost_avoided"] > 0 and len(ov["series"]) == 8
    assert {b["key"] for b in ov["by_workload"]} == {r["workload"] for r in runs}
    filtered = await api.ok("GET", "/api/v1/runs?source=api&workload=coding")
    assert all(r["workload"] == "coding" for r in filtered["items"])
    assert (await api.client.get("/api/v1/runs?source=nope")).status_code == 422
    assert (await api.client.get("/api/v1/runs/999999")).status_code == 404


async def test_runs_are_append_only(api: Api, world: World) -> None:
    await api.v1(world.key, "/v1/context/optimize", optimize_body(support_thread(3)))
    async with api.app.state.container.db.engine.begin() as conn:
        with pytest.raises(Exception, match="append-only"):
            await conn.execute(text("DELETE FROM optimization_runs"))


async def test_budget_missed_filter(api: Api, world: World) -> None:
    await api.v1(
        world.key,
        "/v1/context/optimize",
        optimize_body(coding_trace(), max_input_tokens=60, strategy="conservative"),
    )
    await api.v1(world.key, "/v1/context/optimize", optimize_body(support_thread(3)))
    missed = await api.ok("GET", "/api/v1/runs?budget_missed=true")
    assert len(missed["items"]) == 1 and missed["items"][0]["budget_met"] is False


async def test_stored_content_only_when_enabled(api: Api, world: World) -> None:
    rid = (
        await api.v1(world.key, "/v1/context/optimize", optimize_body(support_thread(3)))
    ).json()["run_id"]
    assert (await api.client.get(f"/api/v1/runs/{rid}/content")).status_code == 404
    api.app.state.container.settings.store_content = True
    try:
        rid = (
            await api.v1(world.key, "/v1/context/optimize", optimize_body(support_thread(4)))
        ).json()["run_id"]
    finally:
        api.app.state.container.settings.store_content = False
    content = await api.ok("GET", f"/api/v1/runs/{rid}/content")
    assert content["request"]["model"] == "gpt-4o" and content["response"]["stats"]
    await api.ok(
        "POST",
        "/api/v1/users",
        {"email": "v2@example.test", "name": "V", "role": "viewer", "password": "Viewer-Pass-123"},
    )
    viewer = await login(api.app, {"email": "v2@example.test", "password": "Viewer-Pass-123"})
    try:
        assert (await viewer.get(f"/api/v1/runs/{rid}/content")).status_code == 403
    finally:
        await viewer.aclose()


async def test_benchmark_run_from_dashboard(api: Api) -> None:
    dataset = await api.ok("GET", "/api/v1/benchmarks/dataset")
    assert len(dataset) == 12 and all(c["tokens"] > c["max_input_tokens"] for c in dataset)
    queued = await api.ok("POST", "/api/v1/benchmarks", {"runs_per_case": 1}, status=202)
    assert (await api.client.post("/api/v1/benchmarks", json={})).status_code == 409
    assert await bench.run_once(api.app.state.container) is True
    run = await api.ok("GET", f"/api/v1/benchmarks/{queued['id']}")
    assert run["status"] == "succeeded" and len(run["results"]) == 48
    forge = next(s for s in run["summary"] if s["method"] == "contextforge-balanced")
    assert forge["fact_retention"] >= 0.95 and forge["citation_retention"] == 1.0
    report = await api.client.get(f"/api/v1/benchmarks/{queued['id']}/report.md")
    assert report.status_code == 200 and "simulated" in report.text
    assert (await api.ok("GET", "/api/v1/benchmarks"))[0]["id"] == queued["id"]


async def test_abandoned_benchmark_run_does_not_block_new_runs(api: Api) -> None:
    from datetime import UTC, datetime, timedelta

    from contextforge.benchmark_runs.models import BenchmarkRun

    queued = await api.ok("POST", "/api/v1/benchmarks", {"runs_per_case": 1}, status=202)
    async with api.app.state.container.db.sessionmaker() as s:
        row = await s.get(BenchmarkRun, queued["id"])
        assert row is not None
        row.status = "running"
        row.created_at = datetime.now(UTC) - timedelta(hours=1)  # its worker died long ago
        await s.commit()
    again = await api.ok("POST", "/api/v1/benchmarks", {"runs_per_case": 1}, status=202)
    old = await api.ok("GET", f"/api/v1/benchmarks/{queued['id']}")
    assert again["status"] == "queued" and old["status"] == "failed" and "stopped" in old["error"]
