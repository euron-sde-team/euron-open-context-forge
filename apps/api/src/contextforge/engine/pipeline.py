"""The optimization pipeline: ingest, measure, protect, clean, rank, compress, validate, return.

``optimize`` is a pure function of its input (plus the tokenizer registry and the profile
table): no network, no database, no clock in the output except the measured latency. The
HTTP service, the OpenAI-compatible proxy, the job worker and the benchmark all call it.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from contextforge.engine.assemble import Assembled, Assembler
from contextforge.engine.profiles import BUILTIN_PROFILES, Profile, detect_workload
from contextforge.engine.stages import build_units, clean, protect, rank
from contextforge.engine.state import DocState, MsgState, Work
from contextforge.engine.summarizer import ExtractiveSummarizer, Summarizer
from contextforge.engine.text import extract_facts, salient_facts, terms
from contextforge.engine.tokenizers import (
    TokenizerRegistry,
    documents_tokens,
    messages_tokens,
)
from contextforge.engine.types import (
    CitationEntry,
    OptimizeRequest,
    OptimizeResult,
    OptimizeWarning,
    ResolvedWorkload,
    Stats,
    TokenizerInfo,
    TraceStep,
)
from contextforge.engine.validate import citation_problems, structure_problems


class BudgetUnsatisfiableError(Exception):
    """Strict mode: the budget cannot be met without removing protected or required content."""

    def __init__(self, result: OptimizeResult) -> None:
        super().__init__("The budget cannot be met without removing protected content")
        self.result = result


_DEFAULT_REGISTRY = TokenizerRegistry()


def _query(work: Work) -> str:
    if work.options.query:
        return work.options.query
    users = [m.message.text() for m in work.msgs if m.message.role == "user" and m.message.text()]
    if not users:
        return ""
    query = users[-1]
    # A terse follow-up ("and the tests?") borrows the previous turn's terms.
    if len(terms(query)) < 6 and len(users) > 1:
        query = users[-2] + "\n" + query
    return query


class _Clock:
    def __init__(self, work: Work, count: Callable[[], int]) -> None:
        self.work = work
        self.count = count
        self.tokens = count()

    @contextmanager
    def stage(self, name: str, *, recount: bool = True) -> Iterator[TraceStep]:
        step = TraceStep(stage=name, tokens_before=self.tokens, tokens_after=self.tokens)
        t0 = time.perf_counter()
        yield step
        step.ms = round((time.perf_counter() - t0) * 1000, 3)
        if recount:
            self.tokens = self.count()
        step.tokens_after = self.tokens
        self.work.trace.append(step)


def _current_tokens(work: Work) -> int:
    from contextforge.engine.assemble import _with_text

    msgs = []
    for m in work.msgs:
        if m.dropped:
            continue
        if m.override is not None or m.clear_content:
            msgs.append(_with_text(m.message, None if m.clear_content else m.override))
        elif m.blocks is not None:
            msgs.append(_with_text(m.message, "\n\n".join(b.text for b in m.blocks)))
        else:
            msgs.append(m.message)
    docs = [d.doc for d in work.docs if d.status == "kept"]
    return messages_tokens(msgs, work.tok) + documents_tokens(docs, work.tok)


def optimize(
    request: OptimizeRequest,
    *,
    registry: TokenizerRegistry | None = None,
    profiles: dict[str, Profile] | None = None,
    summarizer: Summarizer | None = None,
) -> OptimizeResult:
    """Optimize ``request`` and return the result with stats, warnings and a trace.

    Raises :class:`~contextforge.engine.tokenizers.UnsupportedTokenizerError` when the
    model's tokenizer is unknown and estimates are refused, and
    :class:`BudgetUnsatisfiableError` when ``on_budget_failure="error"`` and the budget
    cannot be met safely.
    """
    started = time.perf_counter()
    result = _run(request, registry or _DEFAULT_REGISTRY, profiles, summarizer)
    opts = request.options
    if not result.stats.budget_met and opts.strategy == "balanced":
        escalated = request.model_copy(
            update={"options": opts.model_copy(update={"strategy": "aggressive"})}
        )
        retry = _run(escalated, registry or _DEFAULT_REGISTRY, profiles, summarizer)
        retry.warnings.insert(
            0,
            _warning(
                "strategy_escalated",
                "The balanced strategy could not meet the budget, so aggressive was applied",
            ),
        )
        result = retry
    result.stats.latency_ms = round((time.perf_counter() - started) * 1000, 3)
    if not result.stats.budget_met and opts.on_budget_failure == "error":
        raise BudgetUnsatisfiableError(result)
    return result


def _warning(code: str, message: str, **details: object) -> OptimizeWarning:
    return OptimizeWarning(code=code, message=message, details=details)


def _run(
    request: OptimizeRequest,
    registry: TokenizerRegistry,
    profiles: dict[str, Profile] | None,
    summarizer: Summarizer | None,
) -> OptimizeResult:
    opts = request.options
    table = profiles if profiles is not None else BUILTIN_PROFILES

    # 1. Ingest
    t0 = time.perf_counter()
    tok = registry.resolve(request.model, allow_estimate=opts.allow_estimate)
    work = Work(
        model=request.model,
        options=opts,
        tok=tok,
        msgs=[MsgState(i, m) for i, m in enumerate(request.messages)],
        docs=[DocState(i, d) for i, d in enumerate(request.documents)],
    )
    input_problems = structure_problems(request.messages)
    if input_problems:
        work.warn(
            "input_structure",
            "The input message list has tool call problems; they are passed through unchanged",
            problems=input_problems[:10],
        )
    work.query = _query(work)
    workload: ResolvedWorkload = (
        detect_workload(request.messages, request.documents)
        if opts.workload == "auto"
        else opts.workload
    )
    profile = _profile(table, opts.profile, workload)
    work.trace.append(
        TraceStep(
            stage="ingest",
            tokens_before=0,
            tokens_after=0,
            ms=round((time.perf_counter() - t0) * 1000, 3),
            notes=[
                f"{len(request.messages)} messages, {len(request.documents)} documents",
                f"workload {workload}" + (" (detected)" if opts.workload == "auto" else ""),
                f"profile {profile.name}",
            ],
        )
    )

    # 2. Measure
    t1 = time.perf_counter()
    original = messages_tokens(request.messages, tok) + documents_tokens(request.documents, tok)
    clock = _Clock(work, lambda: _current_tokens(work))
    work.trace.append(
        TraceStep(
            stage="measure",
            tokens_before=original,
            tokens_after=original,
            ms=round((time.perf_counter() - t1) * 1000, 3),
            notes=[f"tokenizer {tok.id}" + ("" if tok.exact else " (estimate)")],
        )
    )
    if not tok.exact:
        work.warn(
            "token_estimate",
            f"No tokenizer is known for {request.model!r}; counts are a conservative estimate",
            tokenizer=tok.id,
        )

    budget = (
        max(0, opts.max_input_tokens - opts.reserve_output_tokens)
        if opts.max_input_tokens is not None
        else None
    )

    # 3. Protect
    with clock.stage("protect", recount=False) as step:
        protect(work)
        reasons: dict[str, int] = {}
        for m in work.msgs:
            if m.protected and m.reason:
                reasons[m.reason] = reasons.get(m.reason, 0) + 1
        step.notes = [f"{k}: {v}" for k, v in sorted(reasons.items())] or ["nothing protected"]
        cited = sum(1 for d in work.docs if d.protected)
        if cited:
            step.notes.append(f"cited documents: {cited}")

    # 4. Clean
    with clock.stage("clean") as step:
        step.items_removed = clean(work)

    # 5. Rank
    with clock.stage("rank") as step:
        units = build_units(work)
        step.items_removed = rank(work, units, profile)
        step.notes = [f"{len(units)} units scored", f"query terms: {len(set(terms(work.query)))}"]

    # 6. Compress
    with clock.stage("compress", recount=False) as step:
        assembler = Assembler(work, units, profile, summarizer or ExtractiveSummarizer())
        assembled = assembler.run(budget)
        clock.tokens = assembled.tokens
        step.items_removed = sum(1 for u in units if not u.keep)
        step.notes = list(assembled.notes)
        if assembled.summary is not None:
            step.notes.append(
                f"summary ({assembled.summary.summarizer}): {assembled.summary.tokens} tokens"
            )
            step.notes.extend(assembled.summary.notes)
            if assembled.summary.fallback_reason:
                work.warn(
                    "llm_summarizer_failed",
                    "The LLM summarizer was unavailable, so the extractive summarizer was used",
                    reason=assembled.summary.fallback_reason,
                )

    # 7. Validate
    with clock.stage("validate", recount=False) as step:
        result = _validate(
            request, work, assembled, original, budget, tok.id, tok.exact, workload, step
        )
    result.trace = work.trace if opts.include_trace else []
    return result


def _profile(table: dict[str, Profile], name: str | None, workload: ResolvedWorkload) -> Profile:
    if name and name in table:
        return table[name]
    return table.get(workload) or BUILTIN_PROFILES[workload]


def _validate(
    request: OptimizeRequest,
    work: Work,
    assembled: Assembled,
    original: int,
    budget: int | None,
    tokenizer_id: str,
    exact: bool,
    workload: ResolvedWorkload,
    step: TraceStep,
) -> OptimizeResult:
    opts = request.options
    final = assembled.tokens
    budget_met = budget is None or final <= budget

    # Citation map: every input id resolves to kept, compressed, merged or dropped.
    for d in work.docs:
        if d.status == "merged":
            work.citation_map[d.doc.id] = CitationEntry(
                status="merged", into=d.into, reason=d.reason
            )
        elif d.status == "dropped":
            work.citation_map[d.doc.id] = CitationEntry(status="dropped", reason=d.reason)
        elif d.protected or d.unit is None or d.unit.keep:
            partial = d.unit is not None and d.unit.partial_text is not None
            work.citation_map[d.doc.id] = CitationEntry(
                status="compressed" if partial else "kept",
                reason="cited by a protected message" if d.protected else None,
            )
        else:
            work.citation_map[d.doc.id] = CitationEntry(status="dropped", reason="budget")
    # A merged duplicate whose keeper was later dropped is dropped too.
    for doc_id, entry in list(work.citation_map.items()):
        if entry.status == "merged" and entry.into is not None:
            target = work.citation_map.get(entry.into)
            if target is None or target.status == "dropped":
                work.citation_map[doc_id] = CitationEntry(
                    status="dropped", reason="duplicate of a dropped document"
                )

    out_texts = [m.text() for m in assembled.messages]
    blob = "\n".join(out_texts) + "\n" + "\n".join(d.text for d in assembled.documents)
    cite_issues = citation_problems(
        request.documents, assembled.documents, work.citation_map, out_texts
    )
    struct_issues = structure_problems(assembled.messages, request.messages)

    referenced: set[str] = set()
    for m in request.messages:
        if m.role not in ("tool", "system", "developer"):
            referenced |= extract_facts(m.text())
    facts_in: set[str] = set()
    for m in request.messages:
        if m.role not in ("system", "developer"):
            facts_in |= salient_facts(
                m.text(), tool=m.role == "tool", referenced=frozenset(referenced)
            )
    retained = sum(1 for f in facts_in if f in blob)

    missing = [
        s for s in opts.must_keep if s not in blob and s not in work.must_keep_missing_in_input
    ]

    if struct_issues:
        work.warn(
            "structure",
            "The optimized message list has structural problems",
            problems=struct_issues[:10],
        )
    if cite_issues:
        work.warn("citations", "Some citations could not be preserved", problems=cite_issues[:10])
    if missing:
        work.warn(
            "required_content_missing",
            "Some must_keep strings could not be kept within the budget",
            missing=missing,
        )
        budget_met = False if opts.on_budget_failure == "error" else budget_met
    if not budget_met and budget is not None:
        protected = sum(1 for m in work.msgs if m.protected)
        work.warn(
            "budget_not_met",
            f"Protected and required content needs {final:,} tokens but the budget is "
            f"{budget:,}. Raise max_input_tokens, lower preserve_recent_messages or shorten "
            "the system prompt",
            optimized_tokens=final,
            budget=budget,
            protected_messages=protected,
        )
    if assembled.summary is not None and opts.summary_role == "system":
        work.warn(
            "summary_in_system_role",
            "The summary quotes conversation and tool text but was placed in the system "
            "role as requested",
        )

    step.notes = [
        f"budget {'met' if budget_met else 'NOT met'}"
        + (f" ({final:,} / {budget:,})" if budget is not None else ""),
        f"facts retained {retained}/{len(facts_in)}",
        f"structure {'ok' if not struct_issues else 'problems'}",
        f"citations {'ok' if not cite_issues else 'problems'}",
    ]
    stats = Stats(
        original_tokens=original,
        optimized_tokens=final,
        tokens_removed=max(0, original - final),
        reduction_percent=round(100.0 * (original - final) / original, 2) if original else 0.0,
        budget=budget,
        budget_met=budget_met,
        messages_in=len(request.messages),
        messages_out=len(assembled.messages),
        documents_in=len(request.documents),
        documents_out=len(assembled.documents),
        facts_total=len(facts_in),
        facts_retained=retained,
        fact_retention=round(retained / len(facts_in), 4) if facts_in else 1.0,
        latency_ms=0.0,
    )
    return OptimizeResult(
        messages=assembled.messages,
        documents=assembled.documents,
        citation_map=work.citation_map,
        citations_preserved=not cite_issues,
        stats=stats,
        tokenizer=TokenizerInfo(id=tokenizer_id, exact=exact, model=request.model),
        strategy=opts.strategy,
        workload=workload,
        allocation=assembled.allocation,
        summary=assembled.summary.text if assembled.summary else None,
        warnings=work.warnings,
    )
