"""The adapter contract and the plain OpenAI-compatible adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from contextforge.core.money import usd_to_nusd


@dataclass(frozen=True, slots=True)
class UpstreamReport:
    model: str | None
    cost_nusd: int | None


class UpstreamAdapter(Protocol):
    kind: str
    # Client request headers forwarded to the upstream, by lower-case prefix.
    passthrough_prefixes: tuple[str, ...]
    # Upstream response headers returned to the client, by lower-case prefix.
    expose_prefixes: tuple[str, ...]

    def report(self, headers: Mapping[str, str], body: Any) -> UpstreamReport: ...


def body_model(body: Any) -> str | None:
    if isinstance(body, dict) and isinstance(body.get("model"), str):
        return str(body["model"])
    return None


def header_cost(headers: Mapping[str, str], name: str) -> int | None:
    value = headers.get(name)
    if not value:
        return None
    try:
        return usd_to_nusd(value)
    except (ValueError, ArithmeticError):
        return None


class OpenAIAdapter:
    """Any OpenAI-compatible API: OpenAI, Azure OpenAI, vLLM, Ollama, LM Studio, Groq."""

    kind = "openai"
    passthrough_prefixes: tuple[str, ...] = ("openai-", "idempotency-key")
    expose_prefixes: tuple[str, ...] = ("openai-", "x-ratelimit-")

    def report(self, headers: Mapping[str, str], body: Any) -> UpstreamReport:
        return UpstreamReport(body_model(body), None)
