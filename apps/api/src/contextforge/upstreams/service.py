"""Upstream endpoints. Credentials are sealed with the row id as encryption context."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from contextforge.audit.service import Actor, audit
from contextforge.core.container import Container
from contextforge.core.errors import AppError, ConflictError, NotFoundError
from contextforge.upstreams.models import Upstream
from contextforge.upstreams.schemas import UpstreamIn, UpstreamOut, UpstreamUpdate


@dataclass(frozen=True, slots=True)
class ResolvedUpstream:
    name: str
    kind: str
    base_url: str
    api_key: str | None
    max_input_tokens: int | None
    strategy: str


def to_out(row: Upstream) -> UpstreamOut:
    return UpstreamOut(
        id=row.id,
        name=row.name,
        kind=row.kind,
        base_url=row.base_url,
        has_api_key=row.sealed_key is not None,
        key_hint=row.key_hint,
        max_input_tokens=row.max_input_tokens,
        strategy=row.strategy,
        enabled=row.enabled,
        created_at=row.created_at,
    )


def _hint(key: str) -> str:
    return "..." + key[-4:] if len(key) >= 8 else "set"


async def list_upstreams(session: AsyncSession) -> list[UpstreamOut]:
    rows = (await session.scalars(select(Upstream).order_by(Upstream.name))).all()
    return [to_out(r) for r in rows]


async def create(
    session: AsyncSession, container: Container, data: UpstreamIn, actor: Actor
) -> UpstreamOut:
    if await session.scalar(select(Upstream.id).where(Upstream.name == data.name)):
        raise ConflictError(f"An upstream named {data.name} already exists", code="upstream_exists")
    row = Upstream(
        id=uuid.uuid4(),
        name=data.name,
        kind=data.kind,
        base_url=data.base_url,
        max_input_tokens=data.max_input_tokens,
        strategy=data.strategy,
        enabled=data.enabled,
    )
    if data.api_key:
        row.sealed_key = await container.sealer.seal(data.api_key, str(row.id))
        row.key_hint = _hint(data.api_key)
    session.add(row)
    audit(session, actor, "upstream.created", "upstream", row.id, name=row.name, kind=row.kind)
    await session.commit()
    await session.refresh(row)
    return to_out(row)


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


async def update(
    session: AsyncSession,
    container: Container,
    upstream_id: uuid.UUID,
    data: UpstreamUpdate,
    actor: Actor,
) -> UpstreamOut:
    row = await session.get(Upstream, upstream_id)
    if row is None:
        raise NotFoundError("Upstream not found")
    changes = data.model_dump(exclude_unset=True, exclude={"api_key", "clear_api_key"})
    old_origin = _origin(row.base_url)
    new_url = changes.get("base_url")
    moved = new_url is not None and _origin(new_url) != old_origin
    if moved and row.sealed_key and not data.api_key and not data.clear_api_key:
        # Repointing a stored key at another host would hand that host the credential.
        raise AppError(
            "Changing the upstream's host needs its API key again (or clear_api_key), so a "
            "stored key is never sent to a new host",
            code="api_key_required",
        )
    for field, value in changes.items():
        if value is not None:
            setattr(row, field, value)
    if data.clear_api_key:
        row.sealed_key, row.key_hint = None, None
    elif data.api_key:
        row.sealed_key = await container.sealer.seal(data.api_key, str(row.id))
        row.key_hint = _hint(data.api_key)
    audit(
        session,
        actor,
        "upstream.updated",
        "upstream",
        row.id,
        fields=sorted([*changes, *(["api_key"] if data.api_key or data.clear_api_key else [])]),
        **({"from_host": old_origin, "to_host": _origin(row.base_url)} if moved else {}),
    )
    await session.commit()
    return to_out(row)


async def delete(session: AsyncSession, upstream_id: uuid.UUID, actor: Actor) -> None:
    row = await session.get(Upstream, upstream_id)
    if row is None:
        raise NotFoundError("Upstream not found")
    from contextforge.keys import service as key_service

    if users := await key_service.names_using(session, upstream=row.name):
        raise ConflictError(
            f"Keys still default to this upstream: {', '.join(users)}. Change them first",
            code="upstream_in_use",
            details={"keys": users},
        )
    await session.delete(row)
    audit(session, actor, "upstream.deleted", "upstream", upstream_id, name=row.name)
    await session.commit()


async def resolve(container: Container, name: str) -> ResolvedUpstream | None:
    """The upstream with its credential opened, cached for the config cache TTL."""

    async def load() -> ResolvedUpstream | None:
        async with container.db.sessionmaker() as session:
            row = await session.scalar(select(Upstream).where(Upstream.name == name))
            if row is None or not row.enabled:
                return None
            key = (
                await container.sealer.open(row.sealed_key, str(row.id)) if row.sealed_key else None
            )
            return ResolvedUpstream(
                row.name, row.kind, row.base_url, key, row.max_input_tokens, row.strategy
            )

    return await container.config_cache.get(f"upstream:{name}", load)


async def first_enabled(container: Container) -> str | None:
    async def load() -> str | None:
        async with container.db.sessionmaker() as session:
            return await session.scalar(
                select(Upstream.name)
                .where(Upstream.enabled.is_(True))
                .order_by(Upstream.created_at)
            )

    return await container.config_cache.get("upstream:first", load)


async def count(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(Upstream)) or 0)


async def exists(session: AsyncSession, name: str) -> bool:
    return await session.scalar(select(Upstream.id).where(Upstream.name == name)) is not None
