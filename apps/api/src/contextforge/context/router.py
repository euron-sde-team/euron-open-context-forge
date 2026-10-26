"""/v1/context: optimize, count tokens, summarize, rank, and background jobs."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from contextforge.context.schemas import (
    CountTokensRequest,
    CountTokensResponse,
    OptimizeResponse,
    RankRequest,
    RankResponse,
    SummarizeRequest,
    SummarizeResponse,
)
from contextforge.context.service import Caller, ContextService
from contextforge.core.deps import ContainerDep
from contextforge.engine.types import OptimizeRequest
from contextforge.jobs import service as jobs
from contextforge.jobs.schemas import JobAccepted, JobOut
from contextforge.keys.dependencies import ServiceKey

router = APIRouter(prefix="/v1/context", tags=["context"])


def _service(container: ContainerDep) -> ContextService:
    return ContextService(container)


Svc = Annotated[ContextService, Depends(_service)]


@router.post(
    "/optimize",
    response_model=OptimizeResponse,
    summary="Optimize messages and documents to fit a token budget",
    response_description="The optimized context with real before and after counts, warnings "
    "and a per-stage trace",
)
async def optimize(
    body: OptimizeRequest, key: ServiceKey, svc: Svc, response: Response
) -> OptimizeResponse:
    resp = await svc.optimize(body, Caller(key, "api"))
    response.headers["x-contextforge-cache"] = "HIT" if resp.cached else "MISS"
    if resp.run_id is not None:
        response.headers["x-contextforge-run-id"] = str(resp.run_id)
    return resp


@router.post(
    "/count-tokens",
    response_model=CountTokensResponse,
    summary="Count tokens with the model's tokenizer (or a marked estimate)",
)
async def count_tokens(body: CountTokensRequest, _: ServiceKey, svc: Svc) -> CountTokensResponse:
    return await svc.count_tokens(body)


@router.post(
    "/summarize", response_model=SummarizeResponse, summary="Structured summary of a conversation"
)
async def summarize(body: SummarizeRequest, _: ServiceKey, svc: Svc) -> SummarizeResponse:
    return await svc.summarize(body)


@router.post(
    "/rank",
    response_model=RankResponse,
    summary="Rank passages by relevance, dropping duplicates and irrelevant ones",
)
async def rank(body: RankRequest, _: ServiceKey, svc: Svc) -> RankResponse:
    return await svc.rank(body)


@router.post(
    "/jobs",
    response_model=JobAccepted,
    status_code=202,
    summary="Optimize in the background (large inputs)",
)
async def create_job(
    body: OptimizeRequest, key: ServiceKey, container: ContainerDep
) -> JobAccepted:
    job = await jobs.create(container, body, Caller(key, "job"))
    return JobAccepted(id=job.id, poll=f"/v1/context/jobs/{job.id}")


@router.get("/jobs/{job_id}", response_model=JobOut, summary="Job status, and the result when done")
async def get_job(job_id: uuid.UUID, key: ServiceKey, container: ContainerDep) -> JobOut:
    return await jobs.get(container, job_id, Caller(key, "job"))
