"""Benchmark runs triggered from the dashboard or the CLI; reports in object storage."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from contextforge.core.db import Base, TimestampMixin, new_id


class BenchmarkRun(TimestampMixin, Base):
    __tablename__ = "benchmark_runs"
    __table_args__ = (
        Index("ix_benchmark_runs_created_at", text("created_at DESC")),
        # At most one queued or running benchmark, enforced by the database.
        Index(
            "ux_benchmark_runs_active",
            text("(true)"),
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    dataset_version: Mapped[str] = mapped_column(String(32), nullable=False)
    cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    runs_per_case: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    summary: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    results: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    report_key: Mapped[str | None] = mapped_column(String(200))
    error: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
