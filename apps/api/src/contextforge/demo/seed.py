"""Demo data: a working ContextForge install with a month of history and live traffic.

* **Configuration** (users, service keys, upstreams, a custom profile) is created through
  the same services the dashboard uses.
* **History**: 30 days of runs. Every historical row is a replay of a *real* engine result:
  the committed benchmark samples are optimized at several budgets, strategies and models,
  and each row copies one of those results (tokens, facts, warnings, trace, allocation);
  only the timestamp, key and source vary. Nothing on the dashboard is an invented number.
* **A benchmark run** is executed so the Benchmarks page has results.
* **Live traffic** then goes through the real API over HTTP: optimizations, background
  jobs, and proxied chat completions to the mock upstream (plain, TokenShield-style with
  one budget refusal, SmartRouter-style with ``model="auto"``), including a cache hit.

The upstreams are the local mock; the TokenShield and SmartRouter ones are simulations of
their documented contracts.
"""

from __future__ import annotations

import asyncio
import os
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from contextforge.audit.service import Actor
from contextforge.benchmark_runs import service as bench
from contextforge.benchmark_runs.models import BenchmarkRun
from contextforge.benchmark_runs.schemas import BenchmarkRunIn
from contextforge.context.service import price_per_million
from contextforge.core.config import get_settings
from contextforge.core.container import Container
from contextforge.core.money import tokens_cost_nusd
from contextforge.core.security import hash_password
from contextforge.engine import OptimizeRequest, optimize
from contextforge.engine.types import OptimizeResult
from contextforge.keys.schemas import KeyCreated, KeyIn
from contextforge.keys.service import create_key
from contextforge.profiles.schemas import ProfileIn, Weights
from contextforge.profiles.service import upsert as upsert_profile
from contextforge.runs.models import OptimizationRun, RunRollupHourly
from contextforge.upstreams.schemas import UpstreamIn
from contextforge.upstreams.service import create as create_upstream
from contextforge.users.models import User

OWNER_EMAIL = "admin@contextforge.local"
KEYS = {
    "Support assistant": ("support", "mock-tokenshield", 1200),
    "Coding agent": ("coding", "mock-openai", 600),
    "Docs search": ("rag", "mock-openai", 900),
    "Research desk": ("research", "mock-smartrouter", 300),
}


@dataclass
class Created:
    keys: dict[str, KeyCreated] = field(default_factory=dict)


@dataclass(frozen=True)
class Replay:
    workload: str
    model: str
    result: OptimizeResult


async def _owner(container: Container, password: str) -> Actor:
    async with container.db.sessionmaker() as session:
        user = await session.scalar(select(User).where(User.email == OWNER_EMAIL))
        if user is None:
            user = User(
                email=OWNER_EMAIL,
                name="Avery Chen",
                role="owner",
                password_hash=hash_password(password),
            )
            session.add(user)
            for email, name, role in (
                ("ana.lima@example.com", "Ana Lima", "admin"),
                ("sam.okafor@example.com", "Sam Okafor", "viewer"),
            ):
                session.add(
                    User(email=email, name=name, role=role, password_hash=hash_password(password))
                )
            await session.commit()
            await session.refresh(user)
        return Actor(user.id, user.email, "owner", "127.0.0.1")


async def _configure(container: Container, actor: Actor, mock_url: str) -> Created:
    created = Created()
    async with container.db.sessionmaker() as session:
        for name, kind, path, budget, strategy in (
            ("mock-openai", "openai", "/v1", 8000, "balanced"),
            ("mock-tokenshield", "tokenshield", "/tokenshield/v1", 6000, "balanced"),
            ("mock-smartrouter", "smartrouter", "/smartrouter/v1", 8000, "aggressive"),
        ):
            await create_upstream(
                session,
                container,
                UpstreamIn(
                    name=name,
                    kind=kind,
                    base_url=mock_url + path,
                    api_key=f"demo-{name}-credential",
                    max_input_tokens=budget,
                    strategy=strategy,
                ),
                actor,
            )
        await upsert_profile(
            session,
            ProfileIn(
                name="incident-review",
                description="Postmortems: tool output and errors first, then the timeline",
                weights=Weights(history=0.25, tool=0.45, documents=0.10, summary=0.20),
                relevance=0.35,
                recency=0.25,
                importance=0.40,
            ),
            actor,
            create=True,
        )
        for name, (profile, upstream, rpm) in KEYS.items():
            created.keys[name] = await create_key(
                session,
                KeyIn(name=name, rpm_limit=rpm, default_profile=profile, default_upstream=upstream),
                container.settings.api_key_pepper,
                actor,
            )
    await container.config_cache.invalidate()
    return created


def _replays() -> list[Replay]:
    """Real engine results over the committed samples, at several budgets and models."""
    _, cases = bench.dataset()
    out: list[Replay] = []
    for case in cases:
        for factor, strategy, model in (
            (1.0, "balanced", case.model),
            (1.6, "balanced", "gpt-4o-mini"),
            (0.8, "aggressive", "claude-sonnet-4-5"),
            (2.5, "conservative", case.model),
        ):
            req = OptimizeRequest(
                model=model,
                messages=case.messages,
                documents=case.documents,
                options={
                    "max_input_tokens": int(case.max_input_tokens * factor),
                    "strategy": strategy,
                },
            )
            out.append(Replay(case.workload, model, optimize(req)))
    return out


async def _history(container: Container, created: Created, days: int) -> int:
    rng = random.Random(7)
    replays = await asyncio.to_thread(_replays)
    by_workload: dict[str, list[Replay]] = {}
    for replay in replays:
        by_workload.setdefault(replay.workload, []).append(replay)
    mix = [("support", 0.3), ("coding", 0.25), ("rag", 0.25), ("agent", 0.1), ("research", 0.1)]
    keys = {k.default_profile: k for k in created.keys.values()}
    now = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for day in range(days, 0, -1):
        weekday = (now - timedelta(days=day)).weekday()
        volume = rng.randint(50, 90) if weekday < 5 else rng.randint(15, 30)
        volume += (days - day) * 2  # adoption grows over the month
        for _ in range(volume):
            workload = rng.choices([w for w, _ in mix], [p for _, p in mix])[0]
            replay = rng.choice(by_workload[workload])
            res = replay.result
            at = now - timedelta(days=day, seconds=rng.randint(0, 86_000))
            key = keys.get(workload) or keys["coding"]
            source = rng.choices(["api", "proxy", "job"], [0.55, 0.4, 0.05])[0]
            cache_hit = rng.random() < 0.08
            price = price_per_million(container, replay.model)
            rows.append(
                {
                    "created_at": at,
                    "source": source,
                    "key_id": key.id,
                    "key_name": key.name,
                    "model": replay.model,
                    "tokenizer": res.tokenizer.id,
                    "exact": res.tokenizer.exact,
                    "workload": res.workload,
                    "profile": key.default_profile,
                    "strategy": res.strategy,
                    "tokens_before": res.stats.original_tokens,
                    "tokens_after": res.stats.optimized_tokens,
                    "budget": res.stats.budget,
                    "budget_met": res.stats.budget_met,
                    "messages_in": res.stats.messages_in,
                    "messages_out": res.stats.messages_out,
                    "documents_in": res.stats.documents_in,
                    "documents_out": res.stats.documents_out,
                    "facts_total": res.stats.facts_total,
                    "facts_retained": res.stats.facts_retained,
                    "citations_preserved": res.citations_preserved,
                    "warnings": [w.code for w in res.warnings],
                    "latency_ms": 0.4 if cache_hit else res.stats.latency_ms,
                    "cache_hit": cache_hit,
                    "cost_avoided_nusd": tokens_cost_nusd(res.stats.tokens_removed, price)
                    if price is not None
                    else None,
                    "upstream": key.default_upstream if source == "proxy" else None,
                    "upstream_model": (
                        "gpt-4o-mini"
                        if key.default_upstream == "mock-smartrouter"
                        else replay.model
                    )
                    if source == "proxy"
                    else None,
                    "upstream_status": 200 if source == "proxy" else None,
                    "summary_tokens": next(
                        (a.used for a in res.allocation if a.category == "summary"), 0
                    ),
                    "allocation": [a.model_dump() for a in res.allocation],
                    "trace": [t.model_dump() for t in res.trace],
                }
            )
    rows.sort(key=lambda r: r["created_at"])
    rollups: dict[tuple[Any, ...], dict[str, Any]] = {}
    for r in rows:
        hour = r["created_at"].replace(minute=0, second=0, microsecond=0)
        k = (hour, r["source"], r["workload"], r["model"])
        agg = rollups.setdefault(
            k,
            {
                "hour": hour,
                "source": r["source"],
                "workload": r["workload"],
                "model": r["model"],
                "runs": 0,
                "tokens_before": 0,
                "tokens_after": 0,
                "budget_missed": 0,
                "facts_total": 0,
                "facts_retained": 0,
                "latency_ms_sum": 0.0,
                "cost_avoided_nusd": 0,
                "cache_hits": 0,
            },
        )
        agg["runs"] += 1
        agg["tokens_before"] += r["tokens_before"]
        agg["tokens_after"] += r["tokens_after"]
        agg["budget_missed"] += 0 if r["budget_met"] else 1
        agg["facts_total"] += r["facts_total"]
        agg["facts_retained"] += r["facts_retained"]
        agg["latency_ms_sum"] += r["latency_ms"]
        agg["cost_avoided_nusd"] += r["cost_avoided_nusd"] or 0
        agg["cache_hits"] += int(r["cache_hit"])
    async with container.db.sessionmaker() as session:
        for i in range(0, len(rows), 500):
            await session.execute(insert(OptimizationRun), rows[i : i + 500])
        await session.execute(insert(RunRollupHourly), list(rollups.values()))
        await session.commit()
    return len(rows)


async def _benchmark(container: Container, actor: Actor) -> None:
    async with container.db.sessionmaker() as session:
        row = await bench.queue(session, BenchmarkRunIn(runs_per_case=2), actor)
    claimed = await bench.claim(container)
    if claimed is not None and claimed.id == row.id:
        await bench.execute(container, claimed)


async def _traffic(api_url: str, created: Created, n: int) -> dict[str, int]:
    rng = random.Random(11)
    stats: dict[str, int] = {}
    _, cases = bench.dataset()
    small = [c for c in cases if c.workload in ("support", "rag", "research")]
    async with httpx.AsyncClient(base_url=api_url, timeout=60) as client:

        def auth(name: str) -> dict[str, str]:
            return {"authorization": f"Bearer {created.keys[name].key}"}

        async def count(label: str, resp: httpx.Response) -> None:
            stats[f"{label}:{resp.status_code}"] = stats.get(f"{label}:{resp.status_code}", 0) + 1

        for i in range(n):
            case = cases[i % len(cases)]
            key = {
                "support": "Support assistant",
                "rag": "Docs search",
                "research": "Research desk",
            }.get(case.workload, "Coding agent")
            body = {
                "model": case.model,
                "messages": [m.model_dump(exclude_none=True) for m in case.messages],
                "documents": [d.model_dump(exclude_none=True) for d in case.documents],
                "options": {
                    "max_input_tokens": int(case.max_input_tokens * rng.choice([1.0, 1.2, 1.5]))
                },
            }
            await count(
                "optimize", await client.post("/v1/context/optimize", json=body, headers=auth(key))
            )
        # The same request again: a result cache hit.
        await count(
            "optimize-repeat",
            await client.post("/v1/context/optimize", json=body, headers=auth(key)),
        )
        # Background jobs for the largest samples.
        for case in sorted(cases, key=lambda c: -len(c.messages))[:3]:
            body = {
                "model": case.model,
                "messages": [m.model_dump(exclude_none=True) for m in case.messages],
                "options": {"max_input_tokens": case.max_input_tokens},
            }
            await count(
                "job",
                await client.post("/v1/context/jobs", json=body, headers=auth("Coding agent")),
            )
        # Proxied chat completions to each simulated upstream.
        for case in small:
            msgs = [m.model_dump(exclude_none=True) for m in case.messages]
            for name, model, extra in (
                ("Support assistant", "gpt-4o-mini", {}),
                ("Research desk", "auto", {}),
                ("Docs search", "gpt-4o", {"x-contextforge-max-input-tokens": "1500"}),
            ):
                await count(
                    "proxy",
                    await client.post(
                        "/v1/chat/completions",
                        headers={**auth(name), **extra},
                        json={"model": model, "messages": msgs},
                    ),
                )
        await count(
            "proxy-over-budget",
            await client.post(
                "/v1/chat/completions",
                headers={**auth("Support assistant"), "x-tokenshield-user": "over-budget"},
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hello"}]},
            ),
        )
    return stats


async def run(days: int = 30, traffic: int = 40, api_url: str = "http://localhost:4330") -> None:
    settings = get_settings()
    password = (
        os.environ.get("DEMO_PASSWORD") or os.environ.get("CF_DEMO_PASSWORD") or "ForgeDemo2026"
    )
    mock_url = os.environ.get("MOCK_LLM_URL", "http://localhost:4350")
    container = Container.build(settings)
    try:
        async with container.db.sessionmaker() as session:
            if await session.scalar(select(func.count()).select_from(BenchmarkRun)):
                print("demo data already present; skipping (make down to reset)")
                return
        actor = await _owner(container, password)
        created = await _configure(container, actor, mock_url)
        rows = await _history(container, created, days)
        print(f"seeded configuration and {rows} historical runs (replayed real engine results)")
        await _benchmark(container, actor)
        print("benchmark: one run completed")
        stats = await _traffic(api_url, created, traffic)
        print("live traffic:", ", ".join(f"{k}={v}" for k, v in sorted(stats.items())))
        public_url = os.environ.get("CONTEXTFORGE_PUBLIC_URL", api_url)
        print()
        print(f"  dashboard login   {OWNER_EMAIL} / {password}")
        print(f"  service key       {created.keys['Coding agent'].key}  (Coding agent)")
        print("  try it:")
        print(f"    curl {public_url}/v1/context/count-tokens -H 'authorization: Bearer <key>' \\")
        print("      -H 'content-type: application/json' \\")
        print(
            '      -d \'{"model":"gpt-4o","text":"Less context. Fewer tokens. Same intelligence."}\''
        )
    finally:
        await container.close()
