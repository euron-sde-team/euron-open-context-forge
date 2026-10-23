"""Euron Open TokenShield as the upstream (https://github.com/euron-sde-team/euron-open-tokenshield).

TokenShield enforces budgets before the provider call and reports the cost of every
request. Forwarding through it puts the optimized request under the same budgets:

* client ``x-tokenshield-*`` headers (user, task id, cache scope) pass through untouched;
* the actual cost is read from ``x-tokenshield-cost-usd`` and stored on the run, next to
  ContextForge's own estimate of the spend it avoided;
* a ``402 budget_exceeded`` (or any TokenShield error) is returned to the client unchanged:
  ContextForge never retries around a budget decision.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from contextforge.integrations.base import UpstreamReport, body_model, header_cost


class TokenShieldAdapter:
    kind = "tokenshield"
    passthrough_prefixes: tuple[str, ...] = ("x-tokenshield-", "idempotency-key")
    expose_prefixes: tuple[str, ...] = ("x-tokenshield-",)

    def report(self, headers: Mapping[str, str], body: Any) -> UpstreamReport:
        return UpstreamReport(body_model(body), header_cost(headers, "x-tokenshield-cost-usd"))
