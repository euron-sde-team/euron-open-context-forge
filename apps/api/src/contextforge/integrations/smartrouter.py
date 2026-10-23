"""Euron Open SmartRouter as the upstream (OpenAI-compatible, ``model="auto"``).

SmartRouter picks the model after ContextForge has shaped the context, so the target
tokenizer is not known in advance: ``auto`` and ``auto:<policy>`` resolve to the
registry's explicit estimate (``exact: false``), which overestimates on purpose so the
budget holds whichever model is chosen. After the call:

* the model actually used is read from ``x-smartrouter-model``;
* the cost from ``x-smartrouter-cost-usd`` (present when SmartRouter knows it);
* client ``x-smartrouter-*`` headers (policy, task) pass through, and SmartRouter's
  routing headers are returned to the client.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from contextforge.integrations.base import UpstreamReport, body_model, header_cost


class SmartRouterAdapter:
    kind = "smartrouter"
    passthrough_prefixes: tuple[str, ...] = ("x-smartrouter-", "idempotency-key")
    expose_prefixes: tuple[str, ...] = ("x-smartrouter-",)

    def report(self, headers: Mapping[str, str], body: Any) -> UpstreamReport:
        model = headers.get("x-smartrouter-model") or body_model(body)
        return UpstreamReport(model, header_cost(headers, "x-smartrouter-cost-usd"))
