from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query, Response

from contextforge.auth.dependencies import Admin, Viewer
from contextforge.core.deps import ContainerDep, SessionDep
from contextforge.core.errors import NotFoundError
from contextforge.core.schemas import Page, decode_cursor, encode_cursor
from contextforge.runs import service
from contextforge.runs.models import OptimizationRun
from contextforge.runs.schemas import Overview, RunDetail, RunOut

router = APIRouter(prefix="/api/v1", tags=["runs"])
SOURCES = r"^(api|proxy|job|playground|benchmark)$"
WORKLOADS = r"^(coding|research|support|agent|rag|chat)$"


@router.get("/runs", response_model=Page[RunOut], summary="Optimization runs, newest first")
async def list_runs(
    _: Viewer,
    session: SessionDep,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    source: str | None = Query(None, pattern=SOURCES),
    workload: str | None = Query(None, pattern=WORKLOADS),
    budget_missed: bool = False,
) -> Page[RunOut]:
    after = decode_cursor(cursor)
    before_id = int(after) if after and after.isdigit() else None
    items, nxt = await service.list_runs(
        session, service.RunFilter(source, workload, budget_missed), before_id, limit
    )
    return Page[RunOut](items=items, next_cursor=encode_cursor(nxt) if nxt else None)


@router.get("/runs/{run_id}", response_model=RunDetail, summary="One run with its trace")
async def get_run(run_id: int, _: Viewer, session: SessionDep) -> RunDetail:
    return await service.get_run(session, run_id)


@router.get(
    "/runs/{run_id}/content", summary="Stored input and output (STORE_CONTENT only, admins)"
)
async def run_content(
    run_id: int, _: Admin, session: SessionDep, container: ContainerDep
) -> dict[str, Any]:
    row = await session.get(OptimizationRun, run_id)
    if row is None or row.content_key is None:
        raise NotFoundError(
            "No content was stored for this run. Set STORE_CONTENT=true to keep inputs",
            code="content_not_stored",
        )
    data: dict[str, Any] = json.loads(await container.storage.get(row.content_key))
    return data


@router.get("/analytics/overview", response_model=Overview, summary="Savings and quality")
async def overview(
    _: Viewer, session: SessionDep, response: Response, days: int = Query(30, ge=1, le=365)
) -> Overview:
    response.headers["cache-control"] = "private, max-age=15"
    return await service.overview(session, days)
