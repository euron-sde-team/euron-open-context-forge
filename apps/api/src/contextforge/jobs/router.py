"""Admin view of jobs. The /v1 job endpoints live with the context router."""

from __future__ import annotations

from fastapi import APIRouter, Query

from contextforge.auth.dependencies import Viewer
from contextforge.core.deps import ContainerDep, SessionDep
from contextforge.jobs import service
from contextforge.jobs.schemas import JobOut

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut], summary="Recent background jobs")
async def list_jobs(
    _: Viewer, session: SessionDep, container: ContainerDep, limit: int = Query(50, ge=1, le=200)
) -> list[JobOut]:
    jobs = await service.list_jobs(session, limit)
    return [await service.to_out(container, j, with_result=False) for j in jobs]
