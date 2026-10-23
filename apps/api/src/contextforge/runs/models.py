"""Optimization runs (append-only) and their hourly rollups."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from contextforge.core.db import Base


class OptimizationRun(Base):
    """One optimization. Stats and trace only; content is stored only with STORE_CONTENT.

    Append-only: a database trigger refuses UPDATE and DELETE.
    """

    __tablename__ = "optimization_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    request_id: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    key_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    key_name: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    tokenizer: Mapped[str] = mapped_column(String(64), nullable=False)
    exact: Mapped[bool] = mapped_column(Boolean, nullable=False)
    workload: Mapped[str] = mapped_column(String(16), nullable=False)
    profile: Mapped[str | None] = mapped_column(String(64))
    strategy: Mapped[str] = mapped_column(String(16), nullable=False)
    tokens_before: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_after: Mapped[int] = mapped_column(Integer, nullable=False)
    budget: Mapped[int | None] = mapped_column(Integer)
    budget_met: Mapped[bool] = mapped_column(Boolean, nullable=False)
    messages_in: Mapped[int] = mapped_column(Integer, nullable=False)
    messages_out: Mapped[int] = mapped_column(Integer, nullable=False)
    documents_in: Mapped[int] = mapped_column(Integer, nullable=False)
    documents_out: Mapped[int] = mapped_column(Integer, nullable=False)
    facts_total: Mapped[int] = mapped_column(Integer, nullable=False)
    facts_retained: Mapped[int] = mapped_column(Integer, nullable=False)
    citations_preserved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Estimated from the list price table; None when the model has no price.
    cost_avoided_nusd: Mapped[int | None] = mapped_column(BigInteger)
    upstream: Mapped[str | None] = mapped_column(String(64))
    upstream_model: Mapped[str | None] = mapped_column(String(200))
    upstream_status: Mapped[int | None] = mapped_column(Integer)
    upstream_cost_nusd: Mapped[int | None] = mapped_column(BigInteger)
    summary_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    allocation: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    trace: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    content_key: Mapped[str | None] = mapped_column(String(200))


class RunRollupHourly(Base):
    """Pre-aggregated counters, upserted in the same transaction as each run."""

    __tablename__ = "run_rollups_hourly"
    hour: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(16), primary_key=True)
    workload: Mapped[str] = mapped_column(String(16), primary_key=True)
    model: Mapped[str] = mapped_column(String(200), primary_key=True)
    runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_before: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tokens_after: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    budget_missed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    facts_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    facts_retained: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    latency_ms_sum: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_avoided_nusd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cache_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
