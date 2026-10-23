"""Upstream LLM endpoints the proxy forwards optimized requests to."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from contextforge.core.db import Base, TimestampMixin, new_id


class Upstream(TimestampMixin, Base):
    __tablename__ = "upstreams"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # openai (any OpenAI-compatible API), tokenshield, smartrouter
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    # Sealed with KMS (or the local master key), bound to this row's id. Never returned.
    sealed_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    key_hint: Mapped[str | None] = mapped_column(String(8))
    max_input_tokens: Mapped[int | None] = mapped_column(Integer)
    strategy: Mapped[str] = mapped_column(String(16), nullable=False, default="balanced")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
