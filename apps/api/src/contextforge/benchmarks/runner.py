"""Benchmark runner: ContextForge strategies against baselines on the same budget.

Methods compared on every case:

* ``contextforge-balanced`` and ``contextforge-aggressive``: the engine;
* ``truncate-oldest``: what most applications do today, keep the system prompt and the
  newest messages that fit, then documents in retrieval order until the budget is full;
* ``no-optimization``: the original context, for reference.

Metrics (all computed, none estimated):

* tokens before and after, with the target model's tokenizer;
* **fact retention**: the share of gold facts present verbatim in the optimized context.
  Strict on purpose: a paraphrase counts as a loss;
* **citation retention**: required document ids still present (directly, or through the
  citation map when a duplicate was merged into a kept document);
* **reader accuracy (simulated)**: a deterministic extractive reader picks the three
  sentences that best match each question by term overlap and is right when the gold
  answer is among them. It is a stand-in for a model, not a model;
* latency: median and p95 of repeated runs, in process.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable

from pydantic import BaseModel

from contextforge.engine import OptimizeRequest, optimize
from contextforge.engine.text import split_sentences, terms
from contextforge.engine.tokenizers import (
    REPLY_PRIMING,
    TokenizerRegistry,
    document_tokens,
    documents_tokens,
    message_tokens,
    messages_tokens,
)
from contextforge.engine.types import Document, Message

from .datasets import Case

METHODS = ("contextforge-balanced", "contextforge-aggressive", "truncate-oldest", "no-optimization")


class CaseResult(BaseModel):
    case_id: str
    workload: str
    method: str
    budget: int
    tokens_before: int
    tokens_after: int
    reduction_percent: float
    budget_met: bool
    fact_retention: float
    facts_missing: list[str]
    citation_retention: float
    reader_accuracy: float
    latency_ms_p50: float
    latency_ms_p95: float


class MethodSummary(BaseModel):
    method: str
    cases: int
    tokens_before: int
    tokens_after: int
    reduction_percent: float
    budget_met: int
    fact_retention: float
    citation_retention: float
    reader_accuracy: float
    latency_ms_p50: float
    latency_ms_p95: float


class BenchmarkReport(BaseModel):
    dataset_version: str
    tokenizer: str
    runs_per_case: int
    results: list[CaseResult]
    summary: list[MethodSummary]


_REGISTRY = TokenizerRegistry()


def _context(messages: list[Message], documents: list[Document]) -> str:
    return (
        "\n".join(m.text() for m in messages)
        + "\n"
        + "\n".join(f"[{d.id}] {d.title or ''} {d.text}" for d in documents)
    )


def reader_answers(context: str, question: str, k: int = 3) -> list[str]:
    """The simulated reader: the k sentences sharing the most terms with the question."""
    q = set(terms(question))
    candidates = [s for line in context.splitlines() for s in split_sentences(line)]
    scored = sorted(enumerate(candidates), key=lambda p: (-len(q & set(terms(p[1]))), p[0]))
    return [s for _, s in scored[:k]]


def truncate_oldest(case: Case) -> tuple[list[Message], list[Document]]:
    tok = _REGISTRY.resolve(case.model)
    budget = case.max_input_tokens
    system = [m for m in case.messages if m.role in ("system", "developer")]
    rest = [m for m in case.messages if m.role not in ("system", "developer")]
    used = REPLY_PRIMING + sum(message_tokens(m, tok) for m in system)
    kept: list[Message] = []
    for m in reversed(rest):
        cost = message_tokens(m, tok)
        if used + cost > budget:
            break
        kept.insert(0, m)
        used += cost
    # Keep the list valid: a tool result whose call was cut goes too.
    calls = {c.id for m in kept for c in (m.tool_calls or [])}
    kept = [m for m in kept if m.role != "tool" or m.tool_call_id in calls]
    docs: list[Document] = []
    for d in case.documents:
        cost = document_tokens(d, tok)
        if used + cost > budget:
            break
        docs.append(d)
        used += cost
    return system + kept, docs


def _measure(fn: Callable[[], object], runs: int) -> tuple[float, float]:
    samples = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    p95 = samples[min(len(samples) - 1, round(0.95 * (len(samples) - 1)))]
    return round(statistics.median(samples), 3), round(p95, 3)


def run_case(case: Case, method: str, runs: int = 5) -> CaseResult:
    tok = _REGISTRY.resolve(case.model)
    before = messages_tokens(case.messages, tok) + documents_tokens(case.documents, tok)
    aliases: dict[str, str] = {}
    if method.startswith("contextforge-"):
        strategy = method.split("-", 1)[1]
        req = OptimizeRequest(
            model=case.model,
            messages=case.messages,
            documents=case.documents,
            options={
                "max_input_tokens": case.max_input_tokens,
                "strategy": strategy,
                "include_trace": False,
            },
        )
        result = optimize(req)
        msgs, docs = result.messages, result.documents
        after, met = result.stats.optimized_tokens, result.stats.budget_met
        aliases = {k: v.into for k, v in result.citation_map.items() if v.into}
        p50, p95 = _measure(lambda: optimize(req), runs)
    elif method == "truncate-oldest":
        msgs, docs = truncate_oldest(case)
        after = messages_tokens(msgs, tok) + documents_tokens(docs, tok)
        met = after <= case.max_input_tokens
        p50, p95 = _measure(lambda: truncate_oldest(case), runs)
    else:
        msgs, docs = case.messages, case.documents
        after, met = before, before <= case.max_input_tokens
        p50 = p95 = 0.0
    context = _context(msgs, docs)
    missing = [f for f in case.gold_facts if f not in context]
    kept_ids = {d.id for d in docs}
    cites_ok = sum(
        1 for c in case.required_citations if c in kept_ids or aliases.get(c) in kept_ids
    )
    correct = sum(
        1 for q in case.questions if any(q.answer in s for s in reader_answers(context, q.question))
    )
    return CaseResult(
        case_id=case.id,
        workload=case.workload,
        method=method,
        budget=case.max_input_tokens,
        tokens_before=before,
        tokens_after=after,
        reduction_percent=round(100 * (before - after) / before, 2) if before else 0.0,
        budget_met=met,
        fact_retention=round(1 - len(missing) / len(case.gold_facts), 4),
        facts_missing=missing,
        citation_retention=round(cites_ok / len(case.required_citations), 4)
        if case.required_citations
        else 1.0,
        reader_accuracy=round(correct / len(case.questions), 4) if case.questions else 1.0,
        latency_ms_p50=p50,
        latency_ms_p95=p95,
    )


def summarize(results: list[CaseResult]) -> list[MethodSummary]:
    out = []
    for method in METHODS:
        rows = [r for r in results if r.method == method]
        if not rows:
            continue
        before = sum(r.tokens_before for r in rows)
        after = sum(r.tokens_after for r in rows)
        out.append(
            MethodSummary(
                method=method,
                cases=len(rows),
                tokens_before=before,
                tokens_after=after,
                reduction_percent=round(100 * (before - after) / before, 2) if before else 0.0,
                budget_met=sum(r.budget_met for r in rows),
                fact_retention=round(statistics.mean(r.fact_retention for r in rows), 4),
                citation_retention=round(statistics.mean(r.citation_retention for r in rows), 4),
                reader_accuracy=round(statistics.mean(r.reader_accuracy for r in rows), 4),
                latency_ms_p50=round(statistics.median(r.latency_ms_p50 for r in rows), 3),
                latency_ms_p95=round(max(r.latency_ms_p95 for r in rows), 3),
            )
        )
    return out


def run(
    cases: list[Case],
    *,
    runs: int = 5,
    methods: tuple[str, ...] = METHODS,
    dataset_version: str = "",
) -> BenchmarkReport:
    results = [run_case(c, m, runs) for c in cases for m in methods]
    return BenchmarkReport(
        dataset_version=dataset_version,
        tokenizer=_REGISTRY.resolve(cases[0].model).id if cases else "",
        runs_per_case=runs,
        results=results,
        summary=summarize(results),
    )


def to_markdown(report: BenchmarkReport) -> str:
    lines = [
        "# ContextForge benchmark results",
        "",
        f"Dataset `{report.dataset_version}` ({len({r.case_id for r in report.results})} "
        f"synthetic cases), tokenizer `{report.tokenizer}`, {report.runs_per_case} timed "
        "runs per case. Regenerate with `make benchmark`.",
        "",
        "Every case has a token budget well below its original size. Fact retention is strict "
        "(the gold fact must appear verbatim). Reader accuracy uses a **simulated** "
        "deterministic extractive reader, not a language model.",
        "",
        "## Summary",
        "",
        "| Method | Tokens before | Tokens after | Reduction | Budget met | Fact retention | "
        "Citation retention | Reader accuracy (simulated) | Latency p50 | Latency p95 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for s in report.summary:
        lines.append(
            f"| {s.method} | {s.tokens_before:,} | {s.tokens_after:,} | "
            f"{s.reduction_percent:.1f}% | {s.budget_met}/{s.cases} | "
            f"{100 * s.fact_retention:.1f}% | {100 * s.citation_retention:.1f}% | "
            f"{100 * s.reader_accuracy:.1f}% | {s.latency_ms_p50:.1f} ms | "
            f"{s.latency_ms_p95:.1f} ms |"
        )
    lines += [
        "",
        "## Per case",
        "",
        "| Case | Workload | Method | Before | After | Budget | Met | Facts | Citations | "
        "Reader | p50 | Missing facts |",
        "| --- | --- | --- | ---: | ---: | ---: | :---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in report.results:
        if r.method == "no-optimization":
            continue
        lines.append(
            f"| {r.case_id} | {r.workload} | {r.method} | {r.tokens_before:,} | "
            f"{r.tokens_after:,} | {r.budget:,} | {'yes' if r.budget_met else 'no'} | "
            f"{100 * r.fact_retention:.0f}% | {100 * r.citation_retention:.0f}% | "
            f"{100 * r.reader_accuracy:.0f}% | {r.latency_ms_p50:.1f} ms | "
            f"{', '.join(r.facts_missing) or 'none'} |"
        )
    return "\n".join(lines) + "\n"
