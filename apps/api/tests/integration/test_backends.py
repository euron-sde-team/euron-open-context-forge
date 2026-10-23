"""The configured storage and key backends are the ones actually used.

``make test-matrix`` reruns the whole suite with TEST_STORAGE=s3 and TEST_KEY_MODE=kms
against Floci (provisioned by the local-floci Terraform) and with TEST_CACHE=memory, so
every other test also runs on every backend; these assert the wiring itself.
"""

from __future__ import annotations

import os

import pytest

from contextforge.core.kv import MemoryKV, RedisKV
from contextforge.core.sealing import KmsSealer, LocalSealer
from contextforge.core.storage import LocalStorage, S3Storage
from tests.integration.conftest import Api, World, optimize_body
from tests.unit.engine.fixtures import coding_trace

pytestmark = pytest.mark.integration


async def test_backends_match_the_matrix(api: Api) -> None:
    c = api.app.state.container
    storage = os.environ.get("TEST_STORAGE", "local")
    keys = os.environ.get("TEST_KEY_MODE", "local")
    cache = os.environ.get("TEST_CACHE", "redis")
    assert isinstance(c.storage, S3Storage if storage == "s3" else LocalStorage)
    assert isinstance(c.sealer, KmsSealer if keys == "kms" else LocalSealer)
    assert isinstance(c.kv, RedisKV if cache == "redis" else MemoryKV)


async def test_job_payload_round_trips_through_the_storage_backend(api: Api, world: World) -> None:
    job = (await api.v1(world.key, "/v1/context/jobs", optimize_body(coding_trace(2)))).json()
    c = api.app.state.container
    raw = await c.storage.get(f"jobs/{job['id']}/payload.json")
    assert b'"model":"gpt-4o"' in raw


async def test_upstream_secret_round_trips_through_the_key_backend(api: Api, world: World) -> None:
    resp = await api.v1(
        world.key,
        "/v1/chat/completions",
        {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    seen = (await api.mock_stats())["last"]["headers"]
    assert seen["authorization"] == "Bearer upstream-secret-plain-0000"
