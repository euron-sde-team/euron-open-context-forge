"""Prometheus metrics for every domain-relevant counter and latency."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

_MS_BUCKETS = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

OPTIMIZATIONS = Counter(
    "contextforge_optimizations_total",
    "Optimizations by source, workload, strategy applied and whether the budget was met",
    ["source", "workload", "strategy", "budget_met"],
)
TOKENS_IN = Counter("contextforge_tokens_in_total", "Tokens received", ["source"])
TOKENS_OUT = Counter(
    "contextforge_tokens_out_total", "Tokens returned after optimization", ["source"]
)
OPTIMIZE_SECONDS = Histogram(
    "contextforge_optimize_seconds", "Engine time per optimization", ["source"], buckets=_MS_BUCKETS
)
STAGE_SECONDS = Histogram(
    "contextforge_stage_seconds", "Engine time per pipeline stage", ["stage"], buckets=_MS_BUCKETS
)
REDUCTION = Histogram(
    "contextforge_reduction_ratio",
    "Share of input tokens removed",
    buckets=(0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 1.0),
)
FACT_RETENTION = Histogram(
    "contextforge_fact_retention_ratio",
    "Share of critical facts retained",
    buckets=(0.5, 0.8, 0.9, 0.95, 0.99, 1.0),
)
RESULT_CACHE = Counter("contextforge_result_cache_total", "Result cache lookups", ["result"])
WARNINGS = Counter("contextforge_warnings_total", "Warnings returned", ["code"])
DEPENDENCY_ERRORS = Counter(
    "contextforge_dependency_errors_total",
    "Optional dependency failures that were absorbed",
    ["dependency", "operation"],
)
UPSTREAM_REQUESTS = Counter(
    "contextforge_upstream_requests_total",
    "Proxied requests by upstream, kind and status class",
    ["upstream", "kind", "status"],
)
UPSTREAM_SECONDS = Histogram(
    "contextforge_upstream_seconds", "Upstream latency (time to headers)", ["upstream"]
)
ENGINE_BUSY = Counter(
    "contextforge_engine_busy_total", "Requests refused because every engine slot was busy"
)
JOBS = Counter("contextforge_jobs_total", "Background jobs by final status", ["status"])
