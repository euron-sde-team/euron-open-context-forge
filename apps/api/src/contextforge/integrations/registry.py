from __future__ import annotations

from contextforge.integrations.base import OpenAIAdapter, UpstreamAdapter
from contextforge.integrations.smartrouter import SmartRouterAdapter
from contextforge.integrations.tokenshield import TokenShieldAdapter

ADAPTERS: dict[str, UpstreamAdapter] = {
    a.kind: a for a in (OpenAIAdapter(), TokenShieldAdapter(), SmartRouterAdapter())
}


def adapter_for(kind: str) -> UpstreamAdapter:
    return ADAPTERS.get(kind, ADAPTERS["openai"])
