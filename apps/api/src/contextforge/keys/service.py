"""Service key lifecycle. Keys are stored as a peppered HMAC; the plaintext is shown once."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from contextforge.audit.service import Actor, audit
from contextforge.core.errors import AppError, NotFoundError
from contextforge.core.security import generate_api_key
from contextforge.keys.models import ApiKey
from contextforge.keys.schemas import KeyCreated, KeyIn, KeyOut, KeyUpdate
from contextforge.profiles import service as profile_service
from contextforge.upstreams import service as upstream_service


def to_out(key: ApiKey) -> KeyOut:
    return KeyOut(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        display=f"cfk_{key.prefix}_****",
        rpm_limit=key.rpm_limit,
        default_profile=key.default_profile,
        default_upstream=key.default_upstream,
        expires_at=key.expires_at,
        revoked_at=key.revoked_at,
        last_used_at=key.last_used_at,
        created_at=key.created_at,
    )


async def list_keys(session: AsyncSession, include_revoked: bool) -> list[KeyOut]:
    stmt = select(ApiKey).order_by(ApiKey.created_at.desc())
    if not include_revoked:
        stmt = stmt.where(ApiKey.revoked_at.is_(None))
    return [to_out(k) for k in (await session.scalars(stmt)).all()]


async def create_key(session: AsyncSession, data: KeyIn, pepper: str, actor: Actor) -> KeyCreated:
    await _check_defaults(session, data.default_profile, data.default_upstream)
    generated = generate_api_key(pepper)
    key = ApiKey(
        **data.model_dump(),
        prefix=generated.prefix,
        secret_hash=generated.secret_hash,
        created_by=actor.id,
    )
    session.add(key)
    await session.flush()
    await session.refresh(key)
    audit(session, actor, "api_key.created", "api_key", key.id, name=key.name)
    await session.commit()
    return KeyCreated(**to_out(key).model_dump(), key=generated.plaintext)


async def update_key(
    session: AsyncSession, key_id: uuid.UUID, data: KeyUpdate, actor: Actor
) -> KeyOut:
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise NotFoundError("API key not found")
    changes = data.model_dump(exclude_unset=True)
    await _check_defaults(session, changes.get("default_profile"), changes.get("default_upstream"))
    for field, value in changes.items():
        setattr(key, field, value)
    audit(
        session,
        actor,
        "api_key.updated",
        "api_key",
        key.id,
        **{k: str(v) for k, v in changes.items()},
    )
    await session.commit()
    return to_out(key)


async def revoke_key(session: AsyncSession, key_id: uuid.UUID, actor: Actor) -> KeyOut:
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise NotFoundError("API key not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        audit(session, actor, "api_key.revoked", "api_key", key.id, name=key.name)
        await session.commit()
    return to_out(key)


async def count_active(session: AsyncSession) -> int:
    """Keys that are not revoked (expired keys included: they may be renewed)."""
    stmt = select(func.count()).select_from(ApiKey).where(ApiKey.revoked_at.is_(None))
    return int(await session.scalar(stmt) or 0)


async def _check_defaults(session: AsyncSession, profile: str | None, upstream: str | None) -> None:
    """A key's defaults must name a profile and an upstream that exist; otherwise every
    request made with the key would fail later instead of this write failing now."""
    if profile and not await profile_service.exists(session, profile):
        raise AppError(f"There is no profile named {profile!r}", code="unknown_profile")
    if upstream and not await upstream_service.exists(session, upstream):
        raise AppError(f"There is no upstream named {upstream!r}", code="unknown_upstream")


async def names_using(
    session: AsyncSession, *, profile: str | None = None, upstream: str | None = None
) -> list[str]:
    """Active keys whose defaults point at this profile or upstream."""
    stmt = select(ApiKey.name).where(ApiKey.revoked_at.is_(None))
    if profile is not None:
        stmt = stmt.where(ApiKey.default_profile == profile)
    if upstream is not None:
        stmt = stmt.where(ApiKey.default_upstream == upstream)
    return list((await session.scalars(stmt.order_by(ApiKey.name))).all())
