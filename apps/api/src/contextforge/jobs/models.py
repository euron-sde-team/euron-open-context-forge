"""Background optimization jobs. Payloads and results live in object storage."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from contextforge.core.db import Base, TimestampMixin, new_id


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    # queued -> running -> succeeded | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    key_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    payload_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    result_key: Mapped[str | None] = mapped_column(String(200))
    run_id: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
