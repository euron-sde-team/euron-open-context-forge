from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response

from contextforge.auth.dependencies import Admin, Viewer
from contextforge.benchmark_runs import service
from contextforge.benchmark_runs.models import BenchmarkRun
from contextforge.benchmark_runs.schemas import (
    BenchmarkRunDetail,
    BenchmarkRunIn,
    BenchmarkRunOut,
    DatasetCase,
)
from contextforge.core.deps import ContainerDep, SessionDep
from contextforge.core.errors import NotFoundError

router = APIRouter(prefix="/api/v1/benchmarks", tags=["benchmarks"])


@router.get("", response_model=list[BenchmarkRunOut], summary="Benchmark runs, newest first")
async def list_runs(
    _: Viewer, session: SessionDep, limit: int = Query(20, ge=1, le=100)
) -> list[BenchmarkRun]:
    return await service.list_runs(session, limit)


@router.post(
    "",
    response_model=BenchmarkRunOut,
    status_code=202,
    summary="Run the benchmark (executed by the worker)",
)
async def queue_run(body: BenchmarkRunIn, actor: Admin, session: SessionDep) -> BenchmarkRun:
    return await service.queue(session, body, actor)


@router.get("/dataset", response_model=list[DatasetCase], summary="The committed benchmark cases")
async def dataset(_: Viewer, response: Response) -> list[DatasetCase]:
    response.headers["cache-control"] = "private, max-age=300"
    return list(service.dataset_index())


@router.get("/{run_id}", response_model=BenchmarkRunDetail, summary="One run with per-case results")
async def get_run(run_id: uuid.UUID, _: Viewer, session: SessionDep) -> BenchmarkRun:
    row = await session.get(BenchmarkRun, run_id)
    if row is None:
        raise NotFoundError("Benchmark run not found")
    return row


@router.get("/{run_id}/report.md", summary="The run's markdown report")
async def report(
    run_id: uuid.UUID, _: Viewer, session: SessionDep, container: ContainerDep
) -> Response:
    row = await session.get(BenchmarkRun, run_id)
    if row is None or row.report_key is None:
        raise NotFoundError("This run has no report yet")
    return Response(await container.storage.get(row.report_key), media_type="text/markdown")
