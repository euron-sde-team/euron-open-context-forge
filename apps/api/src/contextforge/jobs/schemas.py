from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from contextforge.context.schemas import OptimizeResponse


class JobOut(BaseModel):
    id: uuid.UUID
    status: Literal["queued", "running", "succeeded", "failed"]
    model: str
    payload_bytes: int
    attempts: int
    created_at: datetime
    finished_at: datetime | None
    run_id: int | None
    error: dict[str, Any] | None = None
    result: OptimizeResponse | None = Field(None, description="Present once the job succeeded")


class JobAccepted(BaseModel):
    id: uuid.UUID
    status: str = "queued"
    poll: str = Field(description="GET this path until status is succeeded or failed")
