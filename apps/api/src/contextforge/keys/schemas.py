from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from contextforge.core.schemas import ApiModel

NAME = r"^[a-z0-9][a-z0-9_-]{0,63}$"


class KeyIn(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    rpm_limit: int | None = Field(None, ge=1, le=1_000_000)
    default_profile: str | None = Field(None, pattern=NAME)
    default_upstream: str | None = Field(None, pattern=NAME)
    expires_at: datetime | None = None


class KeyUpdate(ApiModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    rpm_limit: int | None = Field(None, ge=1, le=1_000_000)
    default_profile: str | None = Field(None, pattern=NAME)
    default_upstream: str | None = Field(None, pattern=NAME)
    expires_at: datetime | None = None


class KeyOut(ApiModel):
    id: uuid.UUID
    name: str
    prefix: str
    display: str = Field(description="Safe identifier: cfk_<prefix>_****")
    rpm_limit: int | None
    default_profile: str | None
    default_upstream: str | None
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class KeyCreated(KeyOut):
    key: str = Field(description="The full key. Shown once; store it now")
