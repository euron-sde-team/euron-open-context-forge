"""Recording, listing and analysing optimization runs.

Runs are append-only. Each insert upserts the matching ``run_rollups_hourly`` row in the
same transaction, so dashboards read pre-aggregated counters (one row per hour, source,
workload and model) instead of scanning the raw table, and the two can never disagree.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from contextforge.core.errors import NotFoundError
from contextforge.core.money import nusd_to_usd
from contextforge.runs.models import OptimizationRun, RunRollupHourly
from contextforge.runs.schemas import Breakdown, Overview, Point, RunDetail, RunOut


async def record(session: AsyncSession, run: OptimizationRun) -> int:
    session.add(run)
    await session.flush()
    hour = (run.created_at or datetime.now(UTC)).replace(minute=0, second=0, microsecond=0)
    values = {
        "hour": hour,
        "source": run.source,
        "workload": run.workload,
        "model": run.model[:200],
        "runs": 1,
        "tokens_before": run.tokens_before,
        "tokens_after": run.tokens_after,
        "budget_missed": 0 if run.budget_met else 1,
        "facts_total": run.facts_total,
        "facts_retained": run.facts_retained,
        "latency_ms_sum": run.latency_ms,
        "cost_avoided_nusd": run.cost_avoided_nusd or 0,
        "cache_hits": 1 if run.cache_hit else 0,
    }
    stmt = insert(RunRollupHourly).values(**values)
    t = RunRollupHourly.__table__.c
    stmt = stmt.on_conflict_do_update(
        index_elements=["hour", "source", "workload", "model"],
        set_={
            k: t[k] + stmt.excluded[k]
            for k in values
            if k not in ("hour", "source", "workload", "model")
        },
    )
    await session.execute(stmt)
    await session.commit()
    return run.id


def _out(r: OptimizationRun) -> dict[str, object]:
    return {
        **{c.name: getattr(r, c.name) for c in OptimizationRun.__table__.columns},
        "cost_avoided_usd": nusd_to_usd(r.cost_avoided_nusd)
        if r.cost_avoided_nusd is not None
        else None,
        "upstream_cost_usd": nusd_to_usd(r.upstream_cost_nusd)
        if r.upstream_cost_nusd is not None
        else None,
    }


@dataclass(frozen=True, slots=True)
class RunFilter:
    source: str | None = None
    workload: str | None = None
    budget_missed: bool = False
    key_id: object | None = None


async def list_runs(
    session: AsyncSession, f: RunFilter, before_id: int | None, limit: int
) -> tuple[list[RunOut], int | None]:
    stmt = select(OptimizationRun).order_by(OptimizationRun.id.desc()).limit(limit + 1)
    if before_id is not None:
        stmt = stmt.where(OptimizationRun.id < before_id)
    if f.source:
        stmt = stmt.where(OptimizationRun.source == f.source)
    if f.workload:
        stmt = stmt.where(OptimizationRun.workload == f.workload)
    if f.budget_missed:
        stmt = stmt.where(OptimizationRun.budget_met.is_(False))
    if f.key_id is not None:
        stmt = stmt.where(OptimizationRun.key_id == f.key_id)
    rows = list((await session.scalars(stmt)).all())
    items = [RunOut.model_validate(_out(r)) for r in rows[:limit]]
    return items, (rows[limit - 1].id if len(rows) > limit else None)


async def get_run(session: AsyncSession, run_id: int) -> RunDetail:
    row = await session.get(OptimizationRun, run_id)
    if row is None:
        raise NotFoundError("Run not found")
    return RunDetail.model_validate({**_out(row), "has_content": row.content_key is not None})


def _breakdown(rows: dict[str, list[int]]) -> list[Breakdown]:
    out = [
        Breakdown(
            key=k,
            runs=v[0],
            tokens_before=v[1],
            tokens_after=v[2],
            reduction_percent=round(100 * (v[1] - v[2]) / v[1], 2) if v[1] else 0.0,
        )
        for k, v in rows.items()
    ]
    return sorted(out, key=lambda b: -(b.tokens_before - b.tokens_after))


async def overview(session: AsyncSession, days: int) -> Overview:
    now = datetime.now(UTC)
    start = (now - timedelta(days=days)).replace(minute=0, second=0, microsecond=0)
    prev_start = start - timedelta(days=days)
    rows = (
        await session.scalars(select(RunRollupHourly).where(RunRollupHourly.hour >= prev_start))
    ).all()
    cur = [r for r in rows if r.hour >= start]
    prev = [r for r in rows if r.hour < start]

    def agg(rs: list[RunRollupHourly]) -> dict[str, float]:
        runs = sum(r.runs for r in rs)
        before = sum(r.tokens_before for r in rs)
        after = sum(r.tokens_after for r in rs)
        facts = sum(r.facts_total for r in rs)
        return {
            "runs": runs,
            "tokens_before": before,
            "tokens_after": after,
            "tokens_saved": before - after,
            "reduction_percent": round(100 * (before - after) / before, 2) if before else 0.0,
            "fact_retention": round(sum(r.facts_retained for r in rs) / facts, 4) if facts else 1.0,
            "budget_met_rate": round(1 - sum(r.budget_missed for r in rs) / runs, 4)
            if runs
            else 1.0,
            "cache_hit_rate": round(sum(r.cache_hits for r in rs) / runs, 4) if runs else 0.0,
            "avg_latency_ms": round(sum(r.latency_ms_sum for r in rs) / runs, 2) if runs else 0.0,
            "cost_avoided": nusd_to_usd(sum(r.cost_avoided_nusd for r in rs)),
            "cost_avoided_nusd": sum(r.cost_avoided_nusd for r in rs),
        }

    a = agg(cur)
    bucket_hours = 1 if days <= 2 else 24
    series: dict[datetime, list[int]] = defaultdict(lambda: [0, 0, 0])
    by_w: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    by_s: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    by_m: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for r in cur:
        b = r.hour if bucket_hours == 1 else r.hour.replace(hour=0)
        for target in (series[b], by_w[r.workload], by_s[r.source], by_m[r.model]):
            target[0] += r.runs
            target[1] += r.tokens_before
            target[2] += r.tokens_after
    # A continuous axis: empty buckets are zeros, not gaps.
    points = []
    step = timedelta(hours=bucket_hours)
    cursor = start if bucket_hours == 1 else start.replace(hour=0)
    while cursor <= now:
        v = series.get(cursor, [0, 0, 0])
        points.append(
            Point(
                bucket=cursor,
                runs=v[0],
                tokens_before=v[1],
                tokens_after=v[2],
                tokens_saved=v[1] - v[2],
            )
        )
        cursor += step
    previous = {k: float(v) for k, v in agg(prev).items() if k != "cost_avoided_nusd"}
    return Overview(
        days=days,
        runs=int(a["runs"]),
        tokens_before=int(a["tokens_before"]),
        tokens_after=int(a["tokens_after"]),
        tokens_saved=int(a["tokens_saved"]),
        reduction_percent=a["reduction_percent"],
        fact_retention=a["fact_retention"],
        budget_met_rate=a["budget_met_rate"],
        cache_hit_rate=a["cache_hit_rate"],
        avg_latency_ms=a["avg_latency_ms"],
        cost_avoided=int(a["cost_avoided_nusd"]),
        previous=previous,
        series=points,
        by_workload=_breakdown(by_w),
        by_source=_breakdown(by_s),
        by_model=_breakdown(by_m)[:10],
    )


async def count_runs(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(OptimizationRun)) or 0)
