from __future__ import annotations

from fastapi import APIRouter, Path, Response

from contextforge.auth.dependencies import Admin, Viewer
from contextforge.core.deps import ContainerDep, SessionDep
from contextforge.profiles import service
from contextforge.profiles.schemas import NAME, ProfileIn, ProfileOut

router = APIRouter(prefix="/api/v1/profiles", tags=["profiles"])


@router.get("", response_model=list[ProfileOut], summary="Workload profiles (built-in and custom)")
async def list_profiles(_: Viewer, session: SessionDep) -> list[ProfileOut]:
    return await service.list_profiles(session)


@router.post("", response_model=ProfileOut, status_code=201, summary="Create a custom profile")
async def create_profile(
    body: ProfileIn, actor: Admin, session: SessionDep, container: ContainerDep
) -> ProfileOut:
    out = await service.upsert(session, body, actor, create=True)
    await container.config_cache.invalidate()
    return out


@router.put("/{name}", response_model=ProfileOut, summary="Edit a profile's weights")
async def update_profile(
    body: ProfileIn,
    actor: Admin,
    session: SessionDep,
    container: ContainerDep,
    name: str = Path(pattern=NAME),
) -> ProfileOut:
    body = body.model_copy(update={"name": name})
    out = await service.upsert(session, body, actor, create=False)
    await container.config_cache.invalidate()
    return out


@router.delete(
    "/{name}", status_code=204, summary="Delete a custom profile or reset a built-in one"
)
async def delete_profile(
    actor: Admin, session: SessionDep, container: ContainerDep, name: str = Path(pattern=NAME)
) -> Response:
    await service.delete(session, name, actor)
    await container.config_cache.invalidate()
    return Response(status_code=204)
