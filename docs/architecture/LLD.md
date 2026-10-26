# Low-level design

How the pieces fit, module by module. The engine's algorithm has its own document:
[engine.md](engine.md).

## Package layout

```text
apps/api/src/contextforge/
├── engine/          pure pipeline (no I/O): types, tokenizers, text, bm25, toolout,
│                    profiles, summarizer, state, stages, assemble, validate, pipeline
├── benchmarks/      committed datasets, the runner, baselines, the simulated reader
├── context/         /v1/context router, schemas and ContextService (cache, record, metrics)
├── gateway/         /v1/chat/completions and /v1/models: optimize, then forward
├── integrations/    upstream adapters: openai, tokenshield, smartrouter
├── llm/             optional LLM summarizer with a fact guard
├── jobs/            background jobs: create, claim, process, scoped reads
├── runs/            append-only runs, hourly rollups, analytics
├── profiles/        stored profiles merged with the built-ins
├── upstreams/       upstream endpoints with sealed credentials
├── keys/            service keys and the /v1 auth dependency
├── benchmark_runs/  benchmark runs queued from the dashboard, run by the worker
├── playground/      dashboard optimize (session auth) and samples
├── auth/ users/ audit/ system/
├── core/            config, db, kv (Redis or memory), cache, errors, logs, middleware,
│                    security, sealing, storage, aws, money, tracing
├── observability/   Prometheus metrics
├── migrations/      Alembic revisions
├── demo/            the demo seed
├── worker.py        the background worker loop
└── bench.py         make bench
```

Dependencies point inward: routers call services, services call the engine and the data
layer. The engine imports nothing from the rest of the package.

## ContextService.optimize

```text
_prepare        profile = request.profile or key.default_profile (400 unknown_profile if missing)
_cache_key      sha256(canonical request JSON, config version, summarizer model)
_cache_get      KV.get; RedisError or OSError counts as a miss
run_engine      asyncio.to_thread(pipeline.optimize, registry, profile table, summarizer)
                UnsupportedTokenizerError -> 422 unsupported_tokenizer
                BudgetUnsatisfiableError  -> 422 budget_unsatisfiable (details: budget, tokens, warnings)
_response       adds profile name and the cost-avoided estimate (list price table)
_cache_set      only when the serialized response is under RESULT_CACHE_MAX_BYTES
_observe        Prometheus counters and histograms; a budget_not_met JSON log line
record          OptimizationRun + run_rollups_hourly upsert in one transaction;
                content to object storage only with STORE_CONTENT=true
```

A cache hit is still recorded as a run (`cache_hit = true`) with its own latency, so the
dashboard shows real traffic.

## Proxy (`gateway/router.py`)

1. Parse the body (400 `invalid_json`, `invalid_request`); validate messages against the
   engine's `Message` model.
2. Resolve the upstream: `x-contextforge-upstream`, the key's default, `DEFAULT_UPSTREAM`,
   then the first enabled one (400 `no_upstream` or `unknown_upstream`).
3. Unless `x-contextforge-optimize: off`, optimize with the upstream's budget and strategy
   (or the headers'), reserving `max_tokens` for the answer.
4. Forward the body with the upstream's credential and the adapter's pass-through headers.
   `stream: true` relays the upstream's bytes as they arrive; the run is recorded when the
   headers arrive.
5. Return the upstream's status and body unchanged, with `x-contextforge-*` headers and the
   adapter's exposed headers. Timeouts become 504, connection errors 502.

## Jobs

| Step | Detail |
| --- | --- |
| Create | Profile resolved now; payload written to `jobs/<id>/payload.json`; row `queued` |
| Claim | `SELECT ... FOR UPDATE SKIP LOCKED` on the oldest queued job, or a running one whose lease expired; `attempts += 1`, `lease_until = now + JOB_LEASE_S` |
| Process | `ContextService.optimize(..., use_cache=False)`, result to `jobs/<id>/result.json`, `succeeded` with the run id |
| Failure | An `AppError` (deterministic refusal) fails at once with its error body; anything else is retried until the third attempt |
| Read | `GET /v1/context/jobs/{id}` returns 404 unless the job belongs to the calling key |

## Configuration cache and invalidation

`ConfigCache` keeps per-process copies for 5 s with single-flight loading. Every admin
write (keys, profiles, upstreams) calls `invalidate()`, which bumps `cf:cfg:version` in the
KV store; other processes compare the stamp at most once a second. The version is also part
of the result-cache key, so editing a profile can never serve a stale optimization.

## KV store (`core/kv.py`)

`RedisKV` and `MemoryKV` implement `get`, `set`, `incr` and `hit` (rate limits). Redis rate
limits use the sliding-window Lua script from `limits/limiter.py`; the in-process fallback
uses a fixed one-minute window. Callers treat Redis errors as a miss or a pass.

## Worker

One loop: `jobs.run_once`, then `benchmark_runs.run_once`; sleep `JOB_POLL_INTERVAL_S`
when idle. Every model is registered at startup (`import_all_models`) so foreign keys
resolve in a process that never imports the routers. SIGTERM finishes the item in hand.

## Benchmark

`benchmarks/datasets.py` generates the cases from fixed seeds; `data/cases.json` is the
committed output and a unit test checks they match. `benchmarks/runner.py` runs every
method on every case and computes tokens, budget, fact retention, citation retention, a
simulated reader's accuracy and latency percentiles. The dashboard queues a run; the worker
executes it and stores per-case results in Postgres and the markdown report in S3.

## Errors

Every error body is `{"error": {"code", "type", "message", "details"}}`, the OpenAI SDK's
shape plus details. Messages say what to do next ("Raise max_input_tokens or lower
preserve_recent_messages").
