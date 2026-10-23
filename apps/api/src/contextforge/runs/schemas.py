from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from contextforge.core.schemas import ApiModel, Usd


class RunOut(ApiModel):
    id: int
    created_at: datetime
    request_id: str | None
    source: str
    key_id: uuid.UUID | None
    key_name: str | None
    model: str
    tokenizer: str
    exact: bool
    workload: str
    profile: str | None
    strategy: str
    tokens_before: int
    tokens_after: int
    budget: int | None
    budget_met: bool
    messages_in: int
    messages_out: int
    documents_in: int
    documents_out: int
    facts_total: int
    facts_retained: int
    citations_preserved: bool
    warnings: list[str]
    latency_ms: float
    cache_hit: bool
    cost_avoided_usd: float | None
    upstream: str | None
    upstream_model: str | None
    upstream_status: int | None
    upstream_cost_usd: float | None
    summary_tokens: int


class RunDetail(RunOut):
    allocation: list[dict[str, Any]]
    trace: list[dict[str, Any]]
    has_content: bool = Field(description="Input and output stored (STORE_CONTENT=true)")


class Point(ApiModel):
    bucket: datetime
    runs: int
    tokens_before: int
    tokens_after: int
    tokens_saved: int


class Breakdown(ApiModel):
    key: str
    runs: int
    tokens_before: int
    tokens_after: int
    reduction_percent: float


class Overview(ApiModel):
    days: int
    runs: int
    tokens_before: int
    tokens_after: int
    tokens_saved: int
    reduction_percent: float
    fact_retention: float
    budget_met_rate: float
    cache_hit_rate: float
    avg_latency_ms: float
    cost_avoided: Usd = Field(description="Estimated from the list price table")
    previous: dict[str, float] = Field(
        description="Same metrics for the previous period, for trend arrows"
    )
    series: list[Point]
    by_workload: list[Breakdown]
    by_source: list[Breakdown]
    by_model: list[Breakdown]
