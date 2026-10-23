"""Context service: the engine behind the HTTP API, with caching, recording and metrics.

The engine is CPU bound and synchronous, so it runs in a worker thread
(``asyncio.to_thread``) and never blocks the event loop. Around it:

* the **result cache** (Redis, or in-process without Redis) answers an identical request,
  with the same profiles and settings, without running the pipeline again;
* every optimization is **recorded** as an append-only run (stats and trace, never content
  unless ``STORE_CONTENT=true``) with its hourly rollup in the same transaction;
* failures of optional dependencies (Redis, the LLM summarizer) degrade, never fail.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import orjson
from redis.exceptions import RedisError

from contextforge.context.schemas import (
    CountTokensRequest,
    CountTokensResponse,
    OptimizeResponse,
    RankedPassage,
    RankRequest,
    RankResponse,
    SummarizeRequest,
    SummarizeResponse,
)
from contextforge.core.container import Container
from contextforge.core.errors import (
    AppError,
    BudgetUnsatisfiableError,
    UnsupportedTokenizerError,
)
from contextforge.core.logs import request_id_var
from contextforge.core.money import tokens_cost_nusd
from contextforge.engine import pipeline
from contextforge.engine import tokenizers as tk
from contextforge.engine.bm25 import BM25
from contextforge.engine.profiles import Profile
from contextforge.engine.summarizer import (
    ExtractiveSummarizer,
    Summarizer,
    SummaryInput,
    SummaryOutput,
    SummaryUnit,
)
from contextforge.engine.text import (
    digest,
    extract_facts,
    jaccard,
    normalize,
    shingles,
    split_blocks,
)
from contextforge.engine.types import (
    OptimizeRequest,
    OptimizeResult,
    OptimizeWarning,
    TokenizerInfo,
)
from contextforge.keys.dependencies import KeyContext
from contextforge.llm.summarizer import LLMSummarizer
from contextforge.observability import metrics
from contextforge.profiles import service as profiles
from contextforge.runs import service as runs
from contextforge.runs.models import OptimizationRun

log = logging.getLogger("contextforge.context")
CACHE_PREFIX = "cf:res:"


@dataclass(frozen=True, slots=True)
class Caller:
    key: KeyContext | None
    source: str


@dataclass(slots=True)
class UpstreamInfo:
    name: str
    model: str | None = None
    status: int | None = None
    cost_nusd: int | None = None


class _UnconfiguredLLM:
    name = "llm"

    def summarize(self, data: SummaryInput) -> SummaryOutput:
        out = ExtractiveSummarizer().summarize(data)
        out.fallback_reason = "LLM_SUMMARIZER_URL is not configured"
        return out


def price_per_million(container: Container, model: str) -> Decimal | None:
    prices = container.settings.model_prices
    name = model.strip().lower()
    name = name.split("/", 1)[1] if "/" in name else name
    if name in prices:
        return prices[name]
    # Longest known prefix: "gpt-4o-2024-08-06" prices as "gpt-4o".
    matches = [k for k in prices if name.startswith(k)]
    return prices[max(matches, key=len)] if matches else None


def _summarizer(container: Container, kind: str) -> Summarizer:
    s = container.settings
    if kind != "llm":
        return ExtractiveSummarizer()
    if not s.llm_summarizer_url:
        return _UnconfiguredLLM()
    return LLMSummarizer(
        s.llm_summarizer_url, s.llm_summarizer_model, s.llm_summarizer_api_key, s.llm_timeout_s
    )


class ContextService:
    def __init__(self, container: Container) -> None:
        self.c = container

    # ── optimize ─────────────────────────────────────────────────────────────────────
    async def _prepare(
        self, req: OptimizeRequest, caller: Caller
    ) -> tuple[OptimizeRequest, dict[str, Profile], str]:
        table = await profiles.table(self.c)
        name = req.options.profile or (caller.key.default_profile if caller.key else None)
        if name and name not in table:
            raise AppError(
                f"Unknown profile {name!r}. Create it in the dashboard or use one of: "
                + ", ".join(sorted(table)),
                code="unknown_profile",
                details={"profiles": sorted(table)},
            )
        if name and name != req.options.profile:
            req = req.model_copy(
                update={"options": req.options.model_copy(update={"profile": name})}
            )
        return req, table, name or ""

    def _cache_key(self, req: OptimizeRequest) -> str:
        blob = orjson.dumps(req.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)
        h = hashlib.sha256()
        h.update(blob)
        h.update(self.c.config_cache.version.encode())
        h.update(self.c.settings.llm_summarizer_model.encode())
        return CACHE_PREFIX + h.hexdigest()

    async def _cache_get(self, key: str) -> OptimizeResponse | None:
        try:
            raw = await self.c.kv.get(key)
        except (RedisError, OSError):
            metrics.DEPENDENCY_ERRORS.labels("redis", "cache_get").inc()
            return None
        if raw is None:
            metrics.RESULT_CACHE.labels("miss").inc()
            return None
        metrics.RESULT_CACHE.labels("hit").inc()
        return OptimizeResponse.model_validate_json(raw)

    async def _cache_set(self, key: str, resp: OptimizeResponse) -> None:
        raw = resp.model_dump_json(exclude={"run_id", "cached"}).encode()
        if len(raw) > self.c.settings.result_cache_max_bytes:
            return
        try:
            await self.c.kv.set(key, raw, self.c.settings.result_cache_ttl_s)
        except (RedisError, OSError):
            metrics.DEPENDENCY_ERRORS.labels("redis", "cache_set").inc()

    async def run_engine(self, req: OptimizeRequest, table: dict[str, Profile]) -> OptimizeResult:
        summarizer = _summarizer(self.c, req.options.summarizer)
        try:
            return await asyncio.to_thread(
                pipeline.optimize,
                req,
                registry=self.c.tokenizers,
                profiles=table,
                summarizer=summarizer,
            )
        except tk.UnsupportedTokenizerError as exc:
            raise UnsupportedTokenizerError(
                f"No tokenizer is configured for {exc.model!r} and estimates were refused. "
                "Use a supported model name, add a TOKENIZER_ALIASES entry, or allow estimates",
                details={"model": exc.model},
            ) from exc
        except pipeline.BudgetUnsatisfiableError as exc:
            r = exc.result
            raise BudgetUnsatisfiableError(
                f"The context needs at least {r.stats.optimized_tokens:,} tokens but the budget "
                f"is {r.stats.budget:,}. Raise max_input_tokens or lower "
                "preserve_recent_messages",
                details={
                    "optimized_tokens": r.stats.optimized_tokens,
                    "budget": r.stats.budget,
                    "warnings": [w.model_dump() for w in r.warnings],
                },
            ) from exc

    def _response(
        self, req: OptimizeRequest, result: OptimizeResult, profile: str
    ) -> OptimizeResponse:
        price = price_per_million(self.c, req.model)
        avoided = (
            tokens_cost_nusd(result.stats.tokens_removed, price) / 1e9
            if price is not None
            else None
        )
        return OptimizeResponse(
            optimized_messages=result.messages,
            optimized_documents=result.documents,
            citation_map=result.citation_map,
            citations_preserved=result.citations_preserved,
            stats=result.stats,
            tokenizer=result.tokenizer,
            strategy=result.strategy,
            workload=result.workload,
            profile=profile or result.workload,
            allocation=result.allocation,
            summary=result.summary,
            warnings=result.warnings,
            trace=result.trace,
            cost_avoided_usd=round(avoided, 9) if avoided is not None else None,
        )

    async def optimize(
        self,
        req: OptimizeRequest,
        caller: Caller,
        *,
        record: bool = True,
        upstream: UpstreamInfo | None = None,
        use_cache: bool = True,
    ) -> OptimizeResponse:
        started = time.perf_counter()
        req, table, profile = await self._prepare(req, caller)
        key = self._cache_key(req)
        resp = await self._cache_get(key) if use_cache else None
        if resp is not None:
            resp.cached = True
            resp.stats.latency_ms = round((time.perf_counter() - started) * 1000, 3)
        else:
            result = await self.run_engine(req, table)
            resp = self._response(req, result, profile)
            if use_cache:
                await self._cache_set(key, resp)
        self._observe(resp, caller.source)
        if record:
            resp.run_id = await self.record(req, resp, caller, upstream)
        return resp

    def _observe(self, resp: OptimizeResponse, source: str) -> None:
        s = resp.stats
        metrics.OPTIMIZATIONS.labels(
            source, resp.workload, resp.strategy, str(s.budget_met).lower()
        ).inc()
        metrics.TOKENS_IN.labels(source).inc(s.original_tokens)
        metrics.TOKENS_OUT.labels(source).inc(s.optimized_tokens)
        metrics.OPTIMIZE_SECONDS.labels(source).observe(s.latency_ms / 1000)
        if s.original_tokens:
            metrics.REDUCTION.observe(s.tokens_removed / s.original_tokens)
        metrics.FACT_RETENTION.observe(s.fact_retention)
        for w in resp.warnings:
            metrics.WARNINGS.labels(w.code).inc()
        if not resp.cached:
            for step in resp.trace:
                metrics.STAGE_SECONDS.labels(step.stage).observe(step.ms / 1000)

    async def record(
        self,
        req: OptimizeRequest,
        resp: OptimizeResponse,
        caller: Caller,
        upstream: UpstreamInfo | None = None,
    ) -> int | None:
        s = resp.stats
        price = price_per_million(self.c, req.model)
        content_key = None
        if self.c.settings.store_content:
            content_key = f"runs/{datetime.now(UTC):%Y/%m/%d}/{uuid.uuid4()}.json"
            try:
                await self.c.storage.put(
                    content_key,
                    orjson.dumps(
                        {
                            "request": req.model_dump(mode="json"),
                            "response": resp.model_dump(mode="json"),
                        }
                    ),
                    "application/json",
                )
            except Exception:
                log.warning("could not store run content", exc_info=True)
                content_key = None
        summary_tokens = next((a.used for a in resp.allocation if a.category == "summary"), 0)
        run = OptimizationRun(
            created_at=datetime.now(UTC),
            request_id=request_id_var.get(),
            source=caller.source,
            key_id=caller.key.id if caller.key else None,
            key_name=caller.key.name if caller.key else None,
            model=req.model[:200],
            tokenizer=resp.tokenizer.id[:64],
            exact=resp.tokenizer.exact,
            workload=resp.workload,
            profile=resp.profile,
            strategy=resp.strategy,
            tokens_before=s.original_tokens,
            tokens_after=s.optimized_tokens,
            budget=s.budget,
            budget_met=s.budget_met,
            messages_in=s.messages_in,
            messages_out=s.messages_out,
            documents_in=s.documents_in,
            documents_out=s.documents_out,
            facts_total=s.facts_total,
            facts_retained=s.facts_retained,
            citations_preserved=resp.citations_preserved,
            warnings=[w.code for w in resp.warnings],
            latency_ms=s.latency_ms,
            cache_hit=resp.cached,
            cost_avoided_nusd=tokens_cost_nusd(s.tokens_removed, price)
            if price is not None
            else None,
            upstream=upstream.name if upstream else None,
            upstream_model=upstream.model if upstream else None,
            upstream_status=upstream.status if upstream else None,
            upstream_cost_nusd=upstream.cost_nusd if upstream else None,
            summary_tokens=summary_tokens,
            allocation=[a.model_dump() for a in resp.allocation],
            trace=[t.model_dump() for t in resp.trace],
            content_key=content_key,
        )
        try:
            async with self.c.db.sessionmaker() as session:
                return await runs.record(session, run)
        except Exception:
            # The caller already has its optimized context; a lost history row must not
            # turn a correct answer into an error. It is logged and counted instead.
            log.exception("could not record the optimization run")
            metrics.DEPENDENCY_ERRORS.labels("postgres", "record_run").inc()
            return None

    # ── count, summarize, rank ───────────────────────────────────────────────────────
    def _tokenizer(self, model: str, allow_estimate: bool) -> tk.Tokenizer:
        try:
            return self.c.tokenizers.resolve(model, allow_estimate=allow_estimate)
        except tk.UnsupportedTokenizerError as exc:
            raise UnsupportedTokenizerError(
                f"No tokenizer is configured for {model!r} and estimates were refused",
                details={"model": model},
            ) from exc

    async def count_tokens(self, req: CountTokensRequest) -> CountTokensResponse:
        tok = self._tokenizer(req.model, req.allow_estimate)

        def work() -> CountTokensResponse:
            per_msg = [tk.message_tokens(m, tok) for m in req.messages]
            per_doc = [tk.document_tokens(d, tok) for d in req.documents]
            msgs = (tk.REPLY_PRIMING + sum(per_msg)) if per_msg else 0
            text = tok.count(req.text) if req.text else 0
            return CountTokensResponse(
                model=req.model,
                tokenizer=TokenizerInfo(id=tok.id, exact=tok.exact, model=req.model),
                total=msgs + sum(per_doc) + text,
                messages_tokens=msgs,
                documents_tokens=sum(per_doc),
                text_tokens=text,
                per_message=per_msg,
                per_document=per_doc,
            )

        return await asyncio.to_thread(work)

    async def summarize(self, req: SummarizeRequest) -> SummarizeResponse:
        tok = self._tokenizer(req.model, req.allow_estimate)
        summarizer = _summarizer(self.c, req.summarizer)

        def work() -> SummarizeResponse:
            units: list[SummaryUnit] = []
            msgs = [
                m
                for m in req.messages
                if req.include_system or m.role not in ("system", "developer")
            ]
            for i, m in enumerate(msgs):
                for b in split_blocks(m.text()):
                    units.append(SummaryUnit(m.role, i, b.text, b.kind))
            source = tk.messages_tokens(msgs, tok)
            query = req.query or next(
                (m.text() for m in reversed(req.messages) if m.role == "user"), ""
            )
            out = summarizer.summarize(
                SummaryInput(
                    units=units,
                    query=query,
                    budget_tokens=req.max_summary_tokens,
                    count=tok.count,
                    messages_dropped=len(msgs),
                    tokens_dropped=source,
                )
            )
            facts: set[str] = set()
            for u in units:
                facts |= extract_facts(u.text)
            warnings = []
            if out.fallback_reason:
                warnings.append(
                    OptimizeWarning(
                        code="llm_summarizer_failed",
                        message="The LLM summarizer was unavailable, so the extractive "
                        "summarizer was used",
                        details={"reason": out.fallback_reason},
                    )
                )
            if not tok.exact:
                warnings.append(
                    OptimizeWarning(
                        code="token_estimate",
                        message=f"No tokenizer is known for {req.model!r}; counts are an estimate",
                    )
                )
            return SummarizeResponse(
                summary=out.text,
                sections=out.sections,
                summarizer=out.summarizer,
                tokens=out.tokens,
                source_tokens=source,
                facts_total=len(facts),
                facts_covered=sum(1 for f in facts if f in out.text),
                tokenizer=TokenizerInfo(id=tok.id, exact=tok.exact, model=req.model),
                warnings=warnings,
            )

        return await asyncio.to_thread(work)

    async def rank(self, req: RankRequest) -> RankResponse:
        tok = self._tokenizer(req.model, req.allow_estimate)

        def work() -> RankResponse:
            docs = req.passages
            texts = [f"{d.title}\n{d.text}" if d.title else d.text for d in docs]
            rel = BM25(texts).normalized(req.query)
            scores = [d.score for d in docs if d.score is not None]
            lo, hi = (min(scores), max(scores)) if scores else (0.0, 0.0)
            ranked: list[RankedPassage] = []
            for i, d in enumerate(docs):
                score = rel[i]
                if d.score is not None and hi > lo:
                    score = 0.7 * rel[i] + 0.3 * (d.score - lo) / (hi - lo)
                ranked.append(
                    RankedPassage(
                        id=d.id,
                        rank=0,
                        score=round(score, 6),
                        relevance=round(rel[i], 6),
                        tokens=tk.document_tokens(d, tok),
                        source=d.source,
                    )
                )
            order = sorted(range(len(docs)), key=lambda i: (-ranked[i].score, i))
            kept: list[RankedPassage] = []
            dropped: list[RankedPassage] = []
            seen: dict[str, str] = {}
            sigs: list[tuple[str, set[int]]] = []
            used = 0
            for i in order:
                p, d = ranked[i], docs[i]
                if req.deduplicate:
                    h = digest(normalize(d.text))
                    if h in seen:
                        dropped.append(p.model_copy(update={"duplicate_of": seen[h]}))
                        continue
                    sig = shingles(d.text)
                    dup = next((pid for pid, s in sigs if jaccard(sig, s) >= 0.85), None)
                    if dup:
                        dropped.append(p.model_copy(update={"duplicate_of": dup}))
                        continue
                    seen[h] = d.id
                    sigs.append((d.id, sig))
                if p.relevance == 0.0:
                    dropped.append(p)
                    continue
                if req.top_k is not None and len(kept) >= req.top_k:
                    dropped.append(p)
                    continue
                if req.max_tokens is not None and used + p.tokens > req.max_tokens:
                    dropped.append(p)
                    continue
                used += p.tokens
                kept.append(p.model_copy(update={"rank": len(kept) + 1}))
            return RankResponse(
                query=req.query,
                tokenizer=TokenizerInfo(id=tok.id, exact=tok.exact, model=req.model),
                ranked=kept,
                dropped=dropped,
                tokens_selected=used,
            )

        return await asyncio.to_thread(work)
