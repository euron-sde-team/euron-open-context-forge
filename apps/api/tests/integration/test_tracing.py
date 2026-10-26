"""OpenTelemetry: the request path emits spans once an SDK provider is installed."""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tests.integration.conftest import Api, World, optimize_body
from tests.unit.engine.fixtures import support_thread

pytestmark = pytest.mark.integration

EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def provider() -> None:
    sdk = TracerProvider()
    sdk.add_span_processor(SimpleSpanProcessor(EXPORTER))
    trace.set_tracer_provider(sdk)


async def test_optimize_and_proxy_emit_spans(api: Api, world: World) -> None:
    EXPORTER.clear()
    await api.v1(
        world.key, "/v1/context/optimize", optimize_body(support_thread(), max_input_tokens=700)
    )
    await api.v1(
        world.key, "/v1/chat/completions", {"model": "gpt-4o", "messages": support_thread(3)}
    )
    names = [s.name for s in EXPORTER.get_finished_spans()]
    for expected in (
        "context.optimize",
        "context.cache_lookup",
        "context.engine",
        "context.record",
        "proxy.upstream",
    ):
        assert expected in names, expected
    opt = next(s for s in EXPORTER.get_finished_spans() if s.name == "context.optimize")
    assert opt.attributes is not None
    assert opt.attributes["contextforge.budget_met"] is True
    assert (
        opt.attributes["contextforge.tokens_after"] < opt.attributes["contextforge.tokens_before"]
    )
