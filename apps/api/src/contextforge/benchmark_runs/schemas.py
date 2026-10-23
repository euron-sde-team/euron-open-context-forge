from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from contextforge.core.schemas import ApiModel


class BenchmarkRunIn(ApiModel):
    runs_per_case: int = Field(3, ge=1, le=20, description="Timed repetitions per case")


class BenchmarkRunOut(ApiModel):
    id: uuid.UUID
    status: str
    dataset_version: str
    cases: int
    runs_per_case: int
    summary: list[dict[str, Any]]
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class BenchmarkRunDetail(BenchmarkRunOut):
    results: list[dict[str, Any]]


class DatasetCase(ApiModel):
    id: str
    workload: str
    title: str
    description: str
    model: str
    max_input_tokens: int
    tokens: int
    messages: int
    documents: int
    gold_facts: int
    required_citations: int
