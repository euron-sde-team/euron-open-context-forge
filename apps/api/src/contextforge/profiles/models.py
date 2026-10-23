"""Stored workload profiles: custom ones, and overrides of the built-in profiles."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from contextforge.core.db import Base, TimestampMixin, new_id


class WorkloadProfile(TimestampMixin, Base):
    __tablename__ = "workload_profiles"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    weights: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    relevance: Mapped[float] = mapped_column(Float, nullable=False)
    recency: Mapped[float] = mapped_column(Float, nullable=False)
    importance: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
