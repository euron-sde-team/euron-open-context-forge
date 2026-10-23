"""AC11: an unmodified OpenAI SDK, pointed at ContextForge, gets optimized context."""

from __future__ import annotations

import httpx
import pytest
from openai import APIStatusError, AsyncOpenAI

from tests.integration.conftest import Api, World
from tests.unit.engine.fixtures import coding_trace

pytestmark = pytest.mark.integration


def sdk(api: Api, key: str, headers: dict[str, str] | None = None) -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url="http://testserver/v1",
        api_key=key,
        default_headers=headers,
        http_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app)),
        max_retries=0,
    )


async def test_ac11_unmodified_openai_sdk_non_streaming(api: Api, world: World) -> None:
    client = sdk(api, world.key)
    raw = await client.chat.completions.with_raw_response.create(
        model="gpt-4o",
        messages=coding_trace(),
        max_tokens=200,  # type: ignore[arg-type]
    )
    completion = raw.parse()
    assert completion.choices[0].message.content.startswith("Mock answer")
    h = raw.headers
    assert int(h["x-contextforge-optimized-tokens"]) < int(h["x-contextforge-original-tokens"])
    assert int(h["x-contextforge-optimized-tokens"]) <= 4000 - 200
    assert h["x-contextforge-exact"] == "true" and h["x-contextforge-run-id"]
    last = (await api.mock_stats())["last"]
    # The upstream saw the optimized list, and the sealed upstream credential.
    assert last["messages"] < len(coding_trace())
    assert last["headers"]["authorization"] == "Bearer upstream-secret-plain-0000"


async def test_ac11_unmodified_openai_sdk_streaming(api: Api, world: World) -> None:
    client = sdk(api, world.key)
    stream = await client.chat.completions.create(
        model="gpt-4o",
        messages=coding_trace(),
        stream=True,  # type: ignore[arg-type]
    )
    text = "".join([c.choices[0].delta.content or "" async for c in stream if c.choices])
    assert text.startswith("Mock answer. I received")
    run = (await api.ok("GET", "/api/v1/runs?source=proxy"))["items"][0]
    assert run["upstream"] == "plain" and run["upstream_status"] == 200


async def test_proxy_budget_header_and_optimize_off(api: Api, world: World) -> None:
    client = sdk(api, world.key, {"x-contextforge-max-input-tokens": "900"})
    raw = await client.chat.completions.with_raw_response.create(
        model="gpt-4o",
        messages=coding_trace(),  # type: ignore[arg-type]
    )
    assert int(raw.headers["x-contextforge-optimized-tokens"]) <= 900
    off = sdk(api, world.key, {"x-contextforge-optimize": "off"})
    raw = await off.chat.completions.with_raw_response.create(
        model="gpt-4o",
        messages=coding_trace(),  # type: ignore[arg-type]
    )
    assert "x-contextforge-original-tokens" not in raw.headers
    assert (await api.mock_stats())["last"]["messages"] == len(coding_trace())


async def test_proxy_upstream_errors(api: Api, world: World) -> None:
    client = sdk(api, world.key)
    with pytest.raises(APIStatusError) as err:
        await client.chat.completions.create(
            model="fail-500", messages=[{"role": "user", "content": "x"}]
        )
    assert err.value.status_code == 500  # the upstream's own status, passed through
    with pytest.raises(APIStatusError) as err:
        await client.chat.completions.create(
            model="slow", messages=[{"role": "user", "content": "x"}]
        )
    assert err.value.status_code == 504
    await api.ok("POST", "/api/v1/upstreams", {"name": "dead", "base_url": "http://127.0.0.1:9/v1"})
    dead = sdk(api, world.key, {"x-contextforge-upstream": "dead"})
    with pytest.raises(APIStatusError) as err:
        await dead.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": "x"}]
        )
    assert err.value.status_code == 502


async def test_proxy_unknown_and_disabled_upstream(api: Api, world: World) -> None:
    resp = await api.v1(
        world.key,
        "/v1/chat/completions",
        {"model": "gpt-4o", "messages": [{"role": "user", "content": "x"}]},
        {"x-contextforge-upstream": "missing"},
    )
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "unknown_upstream"
    await api.ok("PATCH", f"/api/v1/upstreams/{world.upstreams['plain']}", {"enabled": False})
    resp = await api.v1(
        world.key,
        "/v1/chat/completions",
        {"model": "gpt-4o", "messages": [{"role": "user", "content": "x"}]},
    )
    assert resp.status_code == 400


async def test_proxy_rejects_bad_bodies(api: Api, world: World) -> None:
    async with api.anonymous() as c:
        h = {"authorization": f"Bearer {world.key}", "content-type": "application/json"}
        assert (await c.post("/v1/chat/completions", content=b"{", headers=h)).status_code == 400
        assert (
            await c.post("/v1/chat/completions", json={"model": "x"}, headers=h)
        ).status_code == 400
        resp = await c.post(
            "/v1/chat/completions",
            headers={**h, "x-contextforge-max-input-tokens": "-1"},
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "x"}]},
        )
        assert resp.status_code == 400 and resp.json()["error"]["code"] == "invalid_header"
        resp = await c.post(
            "/v1/chat/completions",
            headers=h,
            json={"model": "gpt-4o", "messages": [{"role": "robot", "content": "x"}]},
        )
        assert resp.status_code == 400


async def test_models_passthrough(api: Api, world: World) -> None:
    models = await sdk(api, world.key).models.list()
    assert "gpt-4o" in {m.id for m in models.data}


async def test_no_upstream_configured(api: Api) -> None:
    key = (await api.ok("POST", "/api/v1/keys", {"name": "lonely"}))["key"]
    resp = await api.v1(
        key,
        "/v1/chat/completions",
        {"model": "gpt-4o", "messages": [{"role": "user", "content": "x"}]},
    )
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "no_upstream"
