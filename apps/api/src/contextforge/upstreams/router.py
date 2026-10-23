from __future__ import annotations

import uuid

from fastapi import APIRouter, Response

from contextforge.auth.dependencies import Admin, Viewer
from contextforge.core.deps import ContainerDep, SessionDep
from contextforge.upstreams import service
from contextforge.upstreams.schemas import UpstreamIn, UpstreamOut, UpstreamUpdate

router = APIRouter(prefix="/api/v1/upstreams", tags=["upstreams"])


@router.get("", response_model=list[UpstreamOut], summary="Upstream LLM endpoints")
async def list_upstreams(_: Viewer, session: SessionDep) -> list[UpstreamOut]:
    return await service.list_upstreams(session)


@router.post("", response_model=UpstreamOut, status_code=201, summary="Add an upstream")
async def create_upstream(
    body: UpstreamIn, actor: Admin, session: SessionDep, container: ContainerDep
) -> UpstreamOut:
    out = await service.create(session, container, body, actor)
    await container.config_cache.invalidate()
    return out


@router.patch("/{upstream_id}", response_model=UpstreamOut, summary="Edit an upstream")
async def update_upstream(
    upstream_id: uuid.UUID,
    body: UpstreamUpdate,
    actor: Admin,
    session: SessionDep,
    container: ContainerDep,
) -> UpstreamOut:
    out = await service.update(session, container, upstream_id, body, actor)
    await container.config_cache.invalidate()
    return out


@router.delete("/{upstream_id}", status_code=204, summary="Remove an upstream")
async def delete_upstream(
    upstream_id: uuid.UUID, actor: Admin, session: SessionDep, container: ContainerDep
) -> Response:
    await service.delete(session, upstream_id, actor)
    await container.config_cache.invalidate()
    return Response(status_code=204)
