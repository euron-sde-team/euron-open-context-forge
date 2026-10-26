"""Workload profiles: built-ins merged with stored overrides and custom profiles.

The merged table is what the engine sees. It is cached per process through the config
cache, so every optimization reads it from memory; any write invalidates it cluster wide.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from contextforge.audit.service import Actor, audit
from contextforge.core.container import Container
from contextforge.core.errors import ConflictError, NotFoundError
from contextforge.engine.profiles import BUILTIN_PROFILES, Profile
from contextforge.profiles.models import WorkloadProfile
from contextforge.profiles.schemas import ProfileIn, ProfileOut, Weights


def _from_row(row: WorkloadProfile) -> Profile:
    base = BUILTIN_PROFILES.get(row.name)
    return Profile(
        name=row.name,
        description=row.description or (base.description if base else ""),
        weights={k: float(v) for k, v in row.weights.items()},  # type: ignore[misc]
        relevance=row.relevance,
        recency=row.recency,
        importance=row.importance,
        builtin=base is not None,
        tags=base.tags if base else (),
    )


async def _rows(container: Container) -> list[WorkloadProfile]:
    async with container.db.sessionmaker() as session:
        return list((await session.scalars(select(WorkloadProfile))).all())


async def table(container: Container) -> dict[str, Profile]:
    async def load() -> dict[str, Profile]:
        merged = dict(BUILTIN_PROFILES)
        for row in await _rows(container):
            merged[row.name] = _from_row(row)
        return merged

    return await container.config_cache.get("profiles", load)


def _out(p: Profile, customized: bool, updated_at: datetime | None) -> ProfileOut:
    w = p.weights
    return ProfileOut(
        name=p.name,
        description=p.description,
        weights=Weights(
            history=w.get("history", 0.0),
            tool=w.get("tool", 0.0),
            documents=w.get("documents", 0.0),
            summary=w.get("summary", 0.0),
        ),
        relevance=p.relevance,
        recency=p.recency,
        importance=p.importance,
        builtin=p.name in BUILTIN_PROFILES,
        customized=customized,
        tags=list(p.tags),
        updated_at=updated_at,
    )


async def list_profiles(session: AsyncSession) -> list[ProfileOut]:
    rows = {r.name: r for r in (await session.scalars(select(WorkloadProfile))).all()}
    out = []
    for name, builtin in BUILTIN_PROFILES.items():
        row = rows.pop(name, None)
        out.append(
            _out(
                _from_row(row) if row else builtin, row is not None, row.updated_at if row else None
            )
        )
    for row in sorted(rows.values(), key=lambda r: r.name):
        out.append(_out(_from_row(row), False, row.updated_at))
    return out


async def upsert(
    session: AsyncSession, data: ProfileIn, actor: Actor, *, create: bool
) -> ProfileOut:
    row = await session.scalar(select(WorkloadProfile).where(WorkloadProfile.name == data.name))
    if create and (row is not None or data.name in BUILTIN_PROFILES):
        raise ConflictError(f"A profile named {data.name} already exists", code="profile_exists")
    if not create and row is None and data.name not in BUILTIN_PROFILES:
        raise NotFoundError("Profile not found")
    values = {
        "description": data.description,
        "weights": data.weights.model_dump(),
        "relevance": data.relevance,
        "recency": data.recency,
        "importance": data.importance,
    }
    if row is None:
        row = WorkloadProfile(name=data.name, **values)
        session.add(row)
    else:
        for k, v in values.items():
            setattr(row, k, v)
    audit(session, actor, "profile.saved", "profile", data.name, **values)
    await session.commit()
    await session.refresh(row)
    return _out(_from_row(row), data.name in BUILTIN_PROFILES, row.updated_at)


async def delete(session: AsyncSession, name: str, actor: Actor) -> None:
    """Delete a custom profile, or reset a built-in profile to its shipped weights."""
    row = await session.scalar(select(WorkloadProfile).where(WorkloadProfile.name == name))
    if row is None:
        if name in BUILTIN_PROFILES:
            return
        raise NotFoundError("Profile not found")
    if name not in BUILTIN_PROFILES:  # a reset built-in still exists afterwards
        from contextforge.keys import service as key_service

        if users := await key_service.names_using(session, profile=name):
            raise ConflictError(
                f"Keys still default to this profile: {', '.join(users)}. Change them first",
                code="profile_in_use",
                details={"keys": users},
            )
    await session.delete(row)
    audit(
        session,
        actor,
        "profile.reset" if name in BUILTIN_PROFILES else "profile.deleted",
        "profile",
        name,
    )
    await session.commit()


async def exists(session: AsyncSession, name: str) -> bool:
    if name in BUILTIN_PROFILES:
        return True
    return (
        await session.scalar(select(WorkloadProfile.name).where(WorkloadProfile.name == name))
        is not None
    )
