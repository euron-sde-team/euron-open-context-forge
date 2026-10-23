"""Dashboard API: auth, roles, keys, profiles, upstreams, audit, system, playground."""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from contextforge.upstreams.models import Upstream
from tests.integration.conftest import OWNER, Api, World, login, optimize_body
from tests.unit.engine.fixtures import support_thread

pytestmark = pytest.mark.integration


async def test_login_failures_and_lockout(api: Api) -> None:
    async with api.anonymous() as c:
        bad = await c.post(
            "/api/v1/auth/login", json={"email": OWNER["email"], "password": "wrong"}
        )
        assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_credentials"
        for _ in range(5):
            await c.post("/api/v1/auth/login", json={"email": OWNER["email"], "password": "wrong"})
        locked = await c.post("/api/v1/auth/login", json=OWNER)
        assert locked.json()["error"]["code"] == "account_locked"
        assert (await c.get("/api/v1/auth/me")).status_code == 401


async def test_cookie_session_requires_csrf_header(api: Api) -> None:
    async with api.anonymous() as c:
        await c.post("/api/v1/auth/login", json=OWNER)
        assert (await c.get("/api/v1/auth/me")).status_code == 200
        resp = await c.post("/api/v1/keys", json={"name": "x"})
        assert resp.status_code == 403 and resp.json()["error"]["code"] == "csrf_required"
        resp = await c.post(
            "/api/v1/keys", json={"name": "x"}, headers={"x-contextforge-csrf": "1"}
        )
        assert resp.status_code == 201


async def test_roles_are_enforced(api: Api) -> None:
    await api.ok(
        "POST",
        "/api/v1/users",
        {
            "email": "viewer@example.test",
            "name": "Vi",
            "role": "viewer",
            "password": "Viewer-Pass-123",
        },
    )
    viewer = await login(api.app, {"email": "viewer@example.test", "password": "Viewer-Pass-123"})
    try:
        assert (await viewer.get("/api/v1/runs")).status_code == 200
        assert (await viewer.get("/api/v1/keys")).status_code == 200
        for method, path, body in (
            ("POST", "/api/v1/keys", {"name": "x"}),
            ("POST", "/api/v1/upstreams", {"name": "x", "base_url": "http://x/v1"}),
            (
                "PUT",
                "/api/v1/profiles/chat",
                {
                    "name": "chat",
                    "weights": {"history": 1, "tool": 0, "documents": 0, "summary": 0},
                    "relevance": 1,
                    "recency": 0,
                    "importance": 0,
                },
            ),
            ("POST", "/api/v1/benchmarks", {}),
            ("GET", "/api/v1/audit", None),
        ):
            resp = await viewer.request(method, path, json=body)
            assert resp.status_code == 403, (method, path, resp.text)
    finally:
        await viewer.aclose()


async def test_service_key_lifecycle(api: Api, world: World) -> None:
    async with api.anonymous() as c:
        assert (
            await c.post("/v1/context/count-tokens", json={"model": "gpt-4o", "text": "x"})
        ).status_code == 401
        bad = await c.post(
            "/v1/context/count-tokens",
            json={"model": "gpt-4o", "text": "x"},
            headers={"authorization": "Bearer cfk_000000000000_nope"},
        )
        assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_api_key"
        garbage = await c.post(
            "/v1/context/count-tokens",
            json={"model": "gpt-4o", "text": "x"},
            headers={"authorization": "Bearer sk-not-ours"},
        )
        assert garbage.status_code == 401
    keys = await api.ok("GET", "/api/v1/keys")
    assert all(k["display"].endswith("_****") and "key" not in k for k in keys)
    await api.ok("POST", f"/api/v1/keys/{world.key_id}/revoke")
    resp = await api.v1(world.key, "/v1/context/count-tokens", {"model": "gpt-4o", "text": "x"})
    assert resp.status_code == 401 and resp.json()["error"]["code"] == "revoked_api_key"
    assert (await api.ok("GET", "/api/v1/keys?include_revoked=true"))[0]["revoked_at"]


async def test_rate_limit_per_key(api: Api) -> None:
    key = (await api.ok("POST", "/api/v1/keys", {"name": "tiny", "rpm_limit": 3}))["key"]
    codes = [
        (
            await api.v1(key, "/v1/context/count-tokens", {"model": "gpt-4o", "text": "x"})
        ).status_code
        for _ in range(5)
    ]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]
    resp = await api.v1(key, "/v1/context/count-tokens", {"model": "gpt-4o", "text": "x"})
    assert int(resp.headers["retry-after"]) >= 1
    assert resp.json()["error"]["details"]["limit_rpm"] == 3


async def test_upstream_credentials_are_sealed_and_never_returned(api: Api, world: World) -> None:
    ups = await api.ok("GET", "/api/v1/upstreams")
    assert all(u["has_api_key"] and u["key_hint"] == "...0000" for u in ups)
    assert "upstream-secret" not in str(ups)
    container = api.app.state.container
    async with container.db.sessionmaker() as s:
        row = await s.scalar(select(Upstream).where(Upstream.name == "plain"))
        assert row is not None and row.sealed_key is not None
        assert b"upstream-secret" not in row.sealed_key
        # Bound to its row: the sealed value does not open under another record id.
        with pytest.raises(Exception):  # noqa: B017 the backend's own decryption error
            await container.sealer.open(row.sealed_key, "some-other-row")
        assert (
            await container.sealer.open(row.sealed_key, str(row.id)) == "upstream-secret-plain-0000"
        )
    await api.ok("PATCH", f"/api/v1/upstreams/{world.upstreams['plain']}", {"clear_api_key": True})
    assert not (await api.ok("GET", "/api/v1/upstreams"))[0]["has_api_key"]
    dup = await api.client.post(
        "/api/v1/upstreams", json={"name": "plain", "base_url": "http://x/v1"}
    )
    assert dup.status_code == 409
    bad = await api.client.post("/api/v1/upstreams", json={"name": "y", "base_url": "ftp://x"})
    assert bad.status_code == 422


async def test_profiles_crud(api: Api) -> None:
    profiles = await api.ok("GET", "/api/v1/profiles")
    names = [p["name"] for p in profiles]
    assert names[:6] == ["coding", "agent", "research", "rag", "support", "chat"]
    body = {
        "name": "triage",
        "description": "x",
        "weights": {"history": 0.5, "tool": 0.5, "documents": 0, "summary": 0},
        "relevance": 0.5,
        "recency": 0.5,
        "importance": 0,
    }
    created = await api.ok("POST", "/api/v1/profiles", body, status=201)
    assert created["builtin"] is False
    assert (await api.client.post("/api/v1/profiles", json=body)).status_code == 409
    zero = {
        **body,
        "name": "zero",
        "weights": {"history": 0, "tool": 0, "documents": 0, "summary": 0},
    }
    assert (await api.client.post("/api/v1/profiles", json=zero)).status_code == 422
    edited = await api.ok("PUT", "/api/v1/profiles/chat", {**body, "name": "chat"})
    assert edited["customized"] is True
    await api.ok("DELETE", "/api/v1/profiles/chat", status=204)
    chat = next(p for p in await api.ok("GET", "/api/v1/profiles") if p["name"] == "chat")
    assert chat["customized"] is False
    await api.ok("DELETE", "/api/v1/profiles/triage", status=204)
    assert (await api.client.delete("/api/v1/profiles/triage")).status_code == 404


async def test_users_keep_an_owner(api: Api) -> None:
    me = await api.ok("GET", "/api/v1/auth/me")
    resp = await api.client.patch(f"/api/v1/users/{me['id']}", json={"role": "viewer"})
    assert resp.status_code == 403
    users = await api.ok("GET", "/api/v1/users")
    assert len(users) == 1


async def test_audit_log_is_append_only(api: Api, world: World) -> None:
    entries = (await api.ok("GET", "/api/v1/audit"))["items"]
    actions = {e["action"] for e in entries}
    assert {"auth.login", "upstream.created", "api_key.created"} <= actions
    async with api.app.state.container.db.engine.begin() as conn:
        with pytest.raises(Exception, match="append-only"):
            await conn.execute(text("UPDATE audit_log SET action = 'x'"))


async def test_system_info_and_health(api: Api) -> None:
    info = await api.ok("GET", "/api/v1/system")
    assert info["cache_backend"] in ("redis", "memory")
    assert info["tokenizers"] == ["o200k_base", "cl100k_base"]
    assert info["llm_summarizer"] is True
    async with api.anonymous() as c:
        assert (await c.get("/healthz")).json() == {"status": "ok"}
        assert (await c.get("/health")).status_code == 200
        ready = await c.get("/readyz")
        assert ready.status_code == 200 and ready.json()["status"] == "ready"
        metrics = (await c.get("/metrics")).text
        assert "contextforge_optimizations_total" in metrics


async def test_playground_and_samples(api: Api) -> None:
    samples = await api.ok("GET", "/api/v1/playground/samples")
    assert len(samples) == 12 and {s["workload"] for s in samples} >= {"coding", "rag", "support"}
    body = await api.ok("GET", f"/api/v1/playground/samples/{samples[3]['id']}")
    result = await api.ok("POST", "/api/v1/playground/optimize", body)
    assert result["stats"]["budget_met"] and result["run_id"]
    run = await api.ok("GET", f"/api/v1/runs/{result['run_id']}")
    assert run["source"] == "playground" and run["key_name"] == f"dashboard:{OWNER['email']}"
    assert (await api.client.get("/api/v1/playground/samples/nope")).status_code == 404
    direct = await api.ok(
        "POST",
        "/api/v1/playground/optimize",
        optimize_body(support_thread(3), max_input_tokens=5000),
    )
    assert direct["stats"]["original_tokens"] > 0
