"""Benchmark runs: queued from the dashboard, executed by the worker, stored for history."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from contextforge.audit.service import Actor, audit
from contextforge.benchmark_runs.models import BenchmarkRun
from contextforge.benchmark_runs.schemas import BenchmarkRunIn, DatasetCase
from contextforge.benchmarks import load_cases
from contextforge.benchmarks.datasets import Case
from contextforge.benchmarks.runner import run, to_markdown
from contextforge.core.container import Container
from contextforge.core.errors import ConflictError, NotFoundError
from contextforge.core.tracing import tracer
from contextforge.engine.tokenizers import TokenizerRegistry, documents_tokens, messages_tokens

log = logging.getLogger("contextforge.benchmarks")


@lru_cache(maxsize=1)
def dataset() -> tuple[str, tuple[Case, ...]]:
    version, cases = load_cases()
    return version, tuple(cases)


@lru_cache(maxsize=1)
def dataset_index() -> tuple[DatasetCase, ...]:
    _, cases = dataset()
    reg = TokenizerRegistry()
    out = []
    for c in cases:
        tok = reg.resolve(c.model)
        out.append(
            DatasetCase(
                id=c.id,
                workload=c.workload,
                title=c.title,
                description=c.description,
                model=c.model,
                max_input_tokens=c.max_input_tokens,
                tokens=messages_tokens(c.messages, tok) + documents_tokens(c.documents, tok),
                messages=len(c.messages),
                documents=len(c.documents),
                gold_facts=len(c.gold_facts),
                required_citations=len(c.required_citations),
            )
        )
    return tuple(out)


def case(case_id: str) -> Case:
    for c in dataset()[1]:
        if c.id == case_id:
            return c
    raise NotFoundError("Sample not found")


async def list_runs(session: AsyncSession, limit: int) -> list[BenchmarkRun]:
    stmt = select(BenchmarkRun).order_by(BenchmarkRun.created_at.desc()).limit(limit)
    return list((await session.scalars(stmt)).all())


# A full run takes seconds; one still "running" after this was abandoned by a worker
# that stopped mid-run, and must not block new runs forever.
STALE_AFTER = timedelta(minutes=15)


async def queue(session: AsyncSession, data: BenchmarkRunIn, actor: Actor) -> BenchmarkRun:
    await session.execute(
        update(BenchmarkRun)
        .where(
            BenchmarkRun.status == "running",
            func.coalesce(BenchmarkRun.started_at, BenchmarkRun.created_at)
            < datetime.now(UTC) - STALE_AFTER,
        )
        .values(
            status="failed",
            error="The worker stopped during this run",
            finished_at=datetime.now(UTC),
        )
    )
    busy = await session.scalar(
        select(BenchmarkRun.id).where(BenchmarkRun.status.in_(("queued", "running")))
    )
    if busy:
        raise ConflictError("A benchmark run is already in progress", code="benchmark_running")
    version, cases = dataset()
    row = BenchmarkRun(
        id=uuid.uuid4(),
        dataset_version=version,
        cases=len(cases),
        runs_per_case=data.runs_per_case,
        requested_by=actor.id,
    )
    session.add(row)
    audit(session, actor, "benchmark.queued", "benchmark", row.id, runs_per_case=data.runs_per_case)
    try:
        await session.commit()
    except IntegrityError as exc:
        # ux_benchmark_runs_active: a concurrent request queued one first.
        await session.rollback()
        raise ConflictError(
            "A benchmark run is already in progress", code="benchmark_running"
        ) from exc
    await session.refresh(row)
    return row


async def claim(container: Container) -> BenchmarkRun | None:
    async with container.db.sessionmaker() as session:
        row = await session.scalar(
            select(BenchmarkRun)
            .where(BenchmarkRun.status == "queued")
            .order_by(BenchmarkRun.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return None
        row.status = "running"
        row.started_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(row)
        return row


async def execute(container: Container, row: BenchmarkRun) -> None:
    with tracer.start_as_current_span("benchmarks.execute") as span:
        span.set_attribute("contextforge.benchmark_run", str(row.id))
        await _execute(container, row)


async def _execute(container: Container, row: BenchmarkRun) -> None:
    try:
        version, cases = dataset()
        report = await asyncio.to_thread(
            run, list(cases), runs=row.runs_per_case, dataset_version=version
        )
        key = f"benchmarks/{row.id}/report.md"
        await container.storage.put(key, to_markdown(report).encode(), "text/markdown")
        values = {
            "status": "succeeded",
            "summary": [s.model_dump() for s in report.summary],
            "results": [r.model_dump() for r in report.results],
            "report_key": key,
        }
    except Exception as exc:
        log.exception("benchmark run failed", extra={"run_id": str(row.id)})
        values = {
            "status": "failed",
            "error": f"The benchmark failed on the worker ({type(exc).__name__}); see its logs",
        }
    async with container.db.sessionmaker() as session:
        # Fenced: a run already marked stale (and possibly replaced) is not overwritten.
        result = await session.execute(
            update(BenchmarkRun)
            .where(
                BenchmarkRun.id == row.id,
                BenchmarkRun.status == "running",
                BenchmarkRun.started_at == row.started_at,
            )
            .values(**values, finished_at=datetime.now(UTC))
        )
        await session.commit()
    if not getattr(result, "rowcount", 0):
        log.warning(
            "benchmark result discarded: run was marked stale", extra={"run_id": str(row.id)}
        )


async def run_once(container: Container) -> bool:
    row = await claim(container)
    if row is None:
        return False
    await execute(container, row)
    return True
