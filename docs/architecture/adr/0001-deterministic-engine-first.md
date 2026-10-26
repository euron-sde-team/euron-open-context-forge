# ADR-0001: The default optimization path is deterministic

- **Status:** Accepted
- **Date:** 2026-10-24

## Context

The common ways to shrink an LLM context either lose information bluntly (truncate the
oldest turns) or spend money and introduce a second source of error (ask a model to
summarise, or score tokens with a small language model as LLMLingua does). A summarising
model can paraphrase away the exact error message, order id or config value the next step
needs, its output changes from run to run, and it needs a network call or a GPU on the
critical path of every request. A context optimizer that is itself expensive, slow or
unpredictable undermines the reason to run one.

## Decision

The engine (`contextforge.engine`) is pure Python with no I/O. Every stage in the default
path is deterministic: tokenizer counting with tiktoken, exact and near-duplicate removal
(normalised hashes and word-shingle Jaccard), BM25 relevance blended with recency and an
importance score, structural reduction of tool output (logs, JSON, stack traces), extractive
sentence selection, and an extractive structured summary of dropped history. The summarizer
default is `extractive`.

A model-based summarizer exists (`summarizer: "llm"`, any OpenAI-compatible endpoint set by
`LLM_SUMMARIZER_URL`), but only when a caller asks for it per request. It sits behind the
same `Summarizer` protocol, its output passes a fact guard, and any failure (including no
endpoint configured) falls back to the extractive summarizer with a
`llm_summarizer_failed` warning.

The engine is importable on its own (`from contextforge import optimize`), so the library,
the REST service and the proxy run the same code.

## Consequences

**Good**
- The same input gives the same output (`test_deterministic`), which makes results
  cacheable by request hash, testable with exact assertions and reproducible in the
  benchmark (`docs/benchmarks/results.md`).
- No GPU, no paid model and no network on the default path: the library works offline
  (acceptance criterion 1) and latency is milliseconds of CPU, not a model round trip.
- Every decision is explainable in the per-stage trace, because each stage is rules and
  scores, not a model's judgement.

**Bad / caveats**
- Extractive selection keeps sentences rather than rewriting them, so on free-form prose
  it reduces less than a good abstractive summary would.
- Relevance is lexical (BM25). Paraphrased relevance is missed until embedding-based
  ranking lands (roadmap).
- The heuristics (fact patterns, problem-signal words in logs) are tuned for English
  technical text.

## Alternatives considered

- **LLM summarisation by default.** Cost, latency, nondeterminism, and silent loss of exact
  values. Kept as an opt-in with a guard.
- **Token-level compression with a small model (LLMLingua-2).** Needs a model runtime and
  produces text that is not human-readable or auditable. Roadmap adapter.
- **Truncation.** Fast and deterministic but loses the user's original requirement; it is
  the baseline the benchmark beats.
