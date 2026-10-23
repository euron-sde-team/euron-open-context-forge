"""Background optimization jobs for inputs too large to hold a request open for.

Payloads and results go to object storage (S3 on AWS and Floci, disk locally); the row keeps
only the object keys, so Postgres never stores multi-megabyte JSON. Workers claim jobs with
``FOR UPDATE SKIP LOCKED`` and a lease, so any number of workers can run and a crashed
worker's job is picked up again when its lease expires. After three attempts a job fails.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import orjson
from sqlalchemy import or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from contextforge.context.schemas import OptimizeResponse
from contextforge.context.service import Caller, ContextService
from contextforge.core.container import Container
from contextforge.core.errors import AppError, NotFoundError
from contextforge.engine.types import OptimizeRequest
from contextforge.jobs.models import Job
from contextforge.jobs.schemas import JobOut
from contextforge.keys.dependencies import KeyContext
from contextforge.observability import metrics

log = logging.getLogger("contextforge.jobs")
MAX_ATTEMPTS = 3


async def create(container: Container, req: OptimizeRequest, caller: Caller) -> Job:
    svc = ContextService(container)
    req, _, _ = await svc._prepare(req, caller)  # bake the key's default profile in now
    job_id = uuid.uuid4()
    payload = orjson.dumps(req.model_dump(mode="json"))
    key = f"jobs/{job_id}/payload.json"
    await container.storage.put(key, payload, "application/json")
    job = Job(
        id=job_id,
        key_id=caller.key.id if caller.key else None,
        model=req.model[:200],
        payload_key=key,
        payload_bytes=len(payload),
    )
    async with container.db.sessionmaker() as session:
        session.add(job)
        await session.commit()
        await session.refresh(job)
    return job


async def get(container: Container, job_id: uuid.UUID, caller: Caller) -> JobOut:
    async with container.db.sessionmaker() as session:
        job = await session.get(Job, job_id)
    key_id = caller.key.id if caller.key else None
    # Structural scoping: a key only ever sees its own jobs.
    if job is None or job.key_id != key_id:
        raise NotFoundError("Job not found")
    return await to_out(container, job, with_result=True)


async def to_out(container: Container, job: Job, *, with_result: bool) -> JobOut:
    result = None
    if with_result and job.status == "succeeded" and job.result_key:
        result = OptimizeResponse.model_validate_json(await container.storage.get(job.result_key))
    return JobOut(
        id=job.id,
        status=job.status,
        model=job.model,
        payload_bytes=job.payload_bytes,
        attempts=job.attempts,
        created_at=job.created_at,
        finished_at=job.finished_at,
        run_id=job.run_id,
        error=job.error,
        result=result,
    )


async def list_jobs(session: AsyncSession, limit: int) -> list[Job]:
    stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
    return list((await session.scalars(stmt)).all())


async def claim(container: Container) -> Job | None:
    lease = timedelta(seconds=container.settings.job_lease_s)
    now = datetime.now(UTC)
    async with container.db.sessionmaker() as session:
        job = await session.scalar(
            select(Job)
            .where(
                or_(
                    Job.status == "queued",
                    (Job.status == "running") & (Job.lease_until < now),
                )
            )
            .order_by(Job.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        job.status = "running"
        job.attempts += 1
        job.lease_until = now + lease
        await session.commit()
        await session.refresh(job)
        return job


async def _finish(container: Container, job_id: uuid.UUID, **values: Any) -> None:
    async with container.db.sessionmaker() as session:
        await session.execute(update(Job).where(Job.id == job_id).values(**values))
        await session.commit()


async def process(container: Container, job: Job) -> None:
    """Run one claimed job to completion (or record why it failed)."""
    try:
        req = OptimizeRequest.model_validate_json(await container.storage.get(job.payload_key))
        caller = Caller(KeyContext(job.key_id, "job", 0, None, None) if job.key_id else None, "job")
        resp = await ContextService(container).optimize(req, caller, use_cache=False)
        result_key = f"jobs/{job.id}/result.json"
        await container.storage.put(result_key, resp.model_dump_json().encode(), "application/json")
        await _finish(
            container,
            job.id,
            status="succeeded",
            result_key=result_key,
            run_id=resp.run_id,
            finished_at=datetime.now(UTC),
            lease_until=None,
        )
        metrics.JOBS.labels("succeeded").inc()
    except AppError as exc:
        # A deterministic refusal (unsupported tokenizer, strict budget): retrying cannot help.
        await _finish(
            container,
            job.id,
            status="failed",
            error=exc.body()["error"],
            finished_at=datetime.now(UTC),
            lease_until=None,
        )
        metrics.JOBS.labels("failed").inc()
    except Exception as exc:
        log.exception("job failed", extra={"job_id": str(job.id)})
        final = job.attempts >= MAX_ATTEMPTS
        await _finish(
            container,
            job.id,
            status="failed" if final else "queued",
            error={"code": "job_error", "message": f"{type(exc).__name__}: {str(exc)[:300]}"},
            finished_at=datetime.now(UTC) if final else None,
            lease_until=None,
        )
        if final:
            metrics.JOBS.labels("failed").inc()


async def run_once(container: Container) -> bool:
    job = await claim(container)
    if job is None:
        return False
    await process(container, job)
    return True


async def queue_depth(session: AsyncSession) -> int:
    value = await session.scalar(text("select count(*) from jobs where status = 'queued'"))
    return int(value or 0)
