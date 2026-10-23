"""Append-only audit trail. Written in the same transaction as the change it describes,
so a change without an audit row cannot be committed."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from contextforge.audit.models import AuditLog


@dataclass(frozen=True, slots=True)
class Actor:
    id: uuid.UUID | None
    email: str | None
    role: str
    ip: str | None = None


def audit(
    session: AsyncSession,
    actor: Actor,
    action: str,
    target_type: str | None = None,
    target_id: object | None = None,
    **details: Any,
) -> None:
    session.add(
        AuditLog(
            actor_id=actor.id,
            actor_email=actor.email,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=details,
            ip=actor.ip,
        )
    )
