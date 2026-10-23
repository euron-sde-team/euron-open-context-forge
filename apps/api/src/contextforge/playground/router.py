"""Dashboard playground: optimize with a session instead of a service key."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from contextforge.auth.dependencies import Viewer
from contextforge.benchmark_runs import service as bench
from contextforge.context.schemas import OptimizeResponse
from contextforge.context.service import Caller, ContextService
from contextforge.core.deps import ContainerDep
from contextforge.engine.types import OptimizeRequest
from contextforge.keys.dependencies import KeyContext

router = APIRouter(prefix="/api/v1/playground", tags=["playground"])


class Sample(BaseModel):
    id: str
    title: str
    workload: str
    description: str
    tokens: int
    max_input_tokens: int


@router.get("/samples", response_model=list[Sample], summary="Sample inputs to try")
async def samples(_: Viewer) -> list[Sample]:
    return [
        Sample(
            id=c.id,
            title=c.title,
            workload=c.workload,
            description=c.description,
            tokens=c.tokens,
            max_input_tokens=c.max_input_tokens,
        )
        for c in bench.dataset_index()
    ]


@router.get("/samples/{sample_id}", summary="A sample as an optimize request body")
async def sample(sample_id: str, _: Viewer) -> dict[str, Any]:
    c = bench.case(sample_id)
    return OptimizeRequest(
        model=c.model,
        messages=c.messages,
        documents=c.documents,
        options={"max_input_tokens": c.max_input_tokens},
    ).model_dump(mode="json", exclude_none=True)


@router.post("/optimize", response_model=OptimizeResponse, summary="Optimize from the dashboard")
async def optimize(
    body: OptimizeRequest, actor: Viewer, container: ContainerDep
) -> OptimizeResponse:
    caller = Caller(KeyContext(None, f"dashboard:{actor.email}", 0, None, None), "playground")
    return await ContextService(container).optimize(body, caller)
