"""AC12: optional TokenShield and SmartRouter adapters.

Contract tests against the mock upstream, which simulates each product's documented
header and error contract (x-tokenshield-*, 402 budget_exceeded; x-smartrouter-*,
model="auto"). Labelled as simulations wherever results are reported.
"""

from __future__ import annotations

import pytest

from tests.integration.conftest import Api, World
from tests.unit.engine.fixtures import coding_trace, support_thread

pytestmark = pytest.mark.integration


async def test_ac12_tokenshield_cost_recorded_and_headers_passed(api: Api, world: World) -> None:
    resp = await api.v1(
        world.key,
        "/v1/chat/completions",
        {"model": "gpt-4o-mini", "messages": support_thread()},
        {
            "x-contextforge-upstream": "shield",
            "x-tokenshield-user": "student-7",
            "x-tokenshield-task-id": "task-1",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["x-tokenshield-cost-usd"]
    assert resp.headers["x-tokenshield-request-id"].startswith("ts_mock_")
    seen = (await api.mock_stats())["last"]["headers"]
    assert seen["x-tokenshield-user"] == "student-7" and seen["x-tokenshield-task-id"] == "task-1"
    run = await api.ok("GET", f"/api/v1/runs/{resp.headers['x-contextforge-run-id']}")
    assert run["upstream"] == "shield"
    assert run["upstream_cost_usd"] == pytest.approx(float(resp.headers["x-tokenshield-cost-usd"]))
    assert run["tokens_after"] < run["tokens_before"]


async def test_ac12_tokenshield_402_passes_through(api: Api, world: World) -> None:
    resp = await api.v1(
        world.key,
        "/v1/chat/completions",
        {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
        {"x-contextforge-upstream": "shield", "x-tokenshield-user": "over-budget"},
    )
    assert resp.status_code == 402
    assert resp.json()["error"]["code"] == "budget_exceeded"
    assert (await api.mock_stats())["calls"]["tokenshield"] == 1  # no retry around a budget
    runs = (await api.ok("GET", "/api/v1/runs?source=proxy"))["items"]
    assert runs[0]["upstream_status"] == 402


async def test_ac12_smartrouter_auto_is_estimated_and_routed_model_recorded(
    api: Api, world: World
) -> None:
    resp = await api.v1(
        world.key,
        "/v1/chat/completions",
        {"model": "auto:cost", "messages": coding_trace()},
        {"x-contextforge-upstream": "router", "x-smartrouter-task": "coding"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["x-contextforge-exact"] == "false"
    assert resp.headers["x-contextforge-tokenizer"].startswith("estimate:")
    assert resp.headers["x-smartrouter-model"] == "gpt-4o-mini"
    assert resp.headers["x-smartrouter-policy"] == "cost"
    assert (await api.mock_stats())["last"]["headers"]["x-smartrouter-task"] == "coding"
    run = await api.ok("GET", f"/api/v1/runs/{resp.headers['x-contextforge-run-id']}")
    assert run["upstream_model"] == "gpt-4o-mini" and run["exact"] is False
    assert run["upstream_cost_usd"] is not None


async def test_adapters_are_optional(api: Api, world: World) -> None:
    """With no TokenShield or SmartRouter anywhere, everything else still works."""
    await api.ok("DELETE", f"/api/v1/upstreams/{world.upstreams['shield']}", status=204)
    await api.ok("DELETE", f"/api/v1/upstreams/{world.upstreams['router']}", status=204)
    resp = await api.v1(
        world.key, "/v1/chat/completions", {"model": "gpt-4o", "messages": support_thread(3)}
    )
    assert resp.status_code == 200
    resp = await api.v1(
        world.key, "/v1/context/optimize", {"model": "gpt-4o", "messages": support_thread(3)}
    )
    assert resp.status_code == 200
