# High-level design

Euron Open ContextForge takes the context an application is about to send to an LLM
(messages, retrieved documents, tool output) and returns the smallest context that still
carries every task-critical fact, with measured before and after token counts, warnings
and a trace of what each stage did.

<p align="center"><img src="../assets/diagrams/architecture.svg" alt="ContextForge architecture" width="100%"></p>

## Goals and non-goals

| Goals | Non-goals (0.1.0) |
| --- | --- |
| Fit a context to a token budget counted with the target model's tokenizer | Learning compression models (LLMLingua style); see the roadmap |
| Keep system instructions, recent turns and critical facts verbatim | Answering questions or calling models on the caller's behalf (the proxy only forwards) |
| Run with no Redis, no vector database and no paid model | Being a budget or routing gateway: TokenShield and SmartRouter do that, ContextForge integrates |
| Three ways in: library, REST API, OpenAI-compatible proxy | Multi-tenant SaaS: one organisation per install |
| Measure quality on every request, and in a reproducible benchmark | |

## Components

| Component | What it does | Where |
| --- | --- | --- |
| Engine | Pure, deterministic pipeline. No I/O. Also a Python library | `apps/api/src/contextforge/engine/` |
| API | `/v1/context/*` (optimize, count-tokens, summarize, rank, jobs) | `context/`, `jobs/` |
| Proxy | `/v1/chat/completions`: optimize, then forward to an upstream | `gateway/`, `integrations/`, `upstreams/` |
| Admin API | `/api/v1/*` for the dashboard: keys, profiles, upstreams, runs, analytics, benchmarks, users, audit | one package per domain |
| Worker | Background jobs and benchmark runs, claimed with `SKIP LOCKED` and leases | `worker.py` |
| Dashboard | Next.js 15: overview, playground, runs, benchmarks, profiles, keys, upstreams | `apps/web/` |
| Postgres | Runs (append-only), hourly rollups, jobs, profiles, upstreams, keys, users, audit | RDS on AWS |
| Redis (optional) | Result cache, per-key rate limits, config version stamp | ElastiCache on AWS |
| Object storage | Job payloads and results, benchmark reports, stored run content | S3 (Floci locally) |
| KMS | Seals upstream credentials, encrypts storage | KMS (Floci locally) |

The engine is the product; everything else is a way to reach it, record what it did, or
tune it. One Python package serves the API, the proxy and the admin API; the same image runs
the worker and the mock LLM.

## Request flow (optimize)

1. Authenticate the `cfk_` key (config cache, no database hit) and check its rate limit.
2. Resolve the workload profile (request, then the key's default, then auto-detection).
3. Look up the result cache: the key is a SHA-256 of the whole request, the config version
   and the summarizer model, so any profile edit invalidates it.
4. On a miss, run the engine in a worker thread (`asyncio.to_thread`): the event loop stays
   free while a 30,000-token trace is processed.
5. Record the run (stats, warnings, trace; never content unless `STORE_CONTENT=true`) and
   upsert its hourly rollup in the same transaction.
6. Return the optimized context with `x-contextforge-*` headers.

The proxy adds two steps: build the optimize request from the chat body and the
`x-contextforge-*` headers, then forward the optimized body (streaming or not) to the
upstream with its sealed credential and record the upstream's status, model and cost.

## Caching layers

| Layer | What is cached | Where | Key | TTL and invalidation |
| --- | --- | --- | --- | --- |
| Result cache | Full optimize responses (without run id) | Redis, or an in-process LRU (2,048 entries and `MEMORY_CACHE_MAX_BYTES`, 64 MB) without Redis | SHA-256 of the canonical request JSON + config version + summarizer model | `RESULT_CACHE_TTL_S` (600 s). Any admin write bumps the config version, so stale results are never served after a profile edit. Responses above `RESULT_CACHE_MAX_BYTES` are not cached; an entry an older release wrote that no longer parses is a miss |
| Config cache | Service key rows, the merged profile table, resolved upstreams (with opened credentials) | Process memory, single flight per key, bounded at 10,000 entries (expired entries evicted first); keys are validated before lookup (hex key prefix, upstream name pattern) so junk tokens never reach the cache or the database | `key:<prefix>`, `profiles`, `upstream:<name>` | 5 s TTL; a load that raced an invalidation is returned but not stored; `cf:cfg:version` stamp checked at most once a second, bumped by every admin write: a revoked key stops working cluster wide within about a second |
| Tokenizer state | BPE tables and per-text token counts | Process memory, loaded at startup and baked into the image | encoding name; text | Process lifetime; the count cache is an LRU of at most 8,192 strings of at most 2,048 characters (about 16 MB), so large prompts are never retained in memory |
| Analytics | Overview aggregates | Postgres `run_rollups_hourly` (written in the run's transaction) + HTTP `Cache-Control: private, max-age=15` | hour, source, workload, model | Exact at write time; the browser may reuse an overview for 15 s |
| Benchmark dataset index | Committed dataset summary | Process memory (`lru_cache`) + HTTP `max-age=300` | none (one dataset) | Process lifetime; the dataset only changes with a release |
| Dashboard | Server state | TanStack Query | per resource (`lib/query-keys.ts`) | `staleTime` per kind (analytics 15 s, config 30 s, live lists 5 s, static 5 min), invalidated on every mutation |

Correctness of invalidation is tested: `test_profile_change_invalidates_cache_and_changes_allocation`
(integration) and the config cache unit tests (`tests/unit/core/test_kv_cache.py`).

## Scalability

- API processes are stateless: state lives in Postgres, Redis and S3. Run N replicas behind
  the load balancer; with Redis the result cache, rate limits and config invalidation are
  shared, without it each replica keeps its own (documented, and exact for one replica).
- The engine is CPU bound. Optimize, count-tokens, summarize and rank run on the engine's own
  thread pool (separate from the one sign-in hashing and storage calls use), at most
  `ENGINE_CONCURRENCY` (4) at once per process; past that a request waits up to `ENGINE_QUEUE_TIMEOUT_S` and then gets
  503 `engine_busy` with `Retry-After`, so a burst of huge inputs cannot starve the process.
  Every stage is linear in the input (sentence extraction counts each sentence once; `/rank`
  near-duplicate checks are capped at 400 passages). Throughput scales with cores and
  replicas (129 cold optimizations per second on a laptop, see the README).
- Workers scale horizontally: `FOR UPDATE SKIP LOCKED` plus a lease means no job or
  benchmark run is claimed twice. The worker renews the lease while a job runs; a crashed
  worker's job is reclaimed when its lease expires, and every write is fenced on the claimed
  attempt, so a worker that lost its lease cannot overwrite the result. A job that keeps
  killing workers fails after three attempts. At most one benchmark is queued or running,
  enforced by a partial unique index.
- Dashboards read hourly rollups, never the raw runs table.

## Failure behaviour

| Dependency down | Effect |
| --- | --- |
| Redis | Optimization continues; cache misses, rate limits pass, `/readyz` reports degraded but stays ready, `contextforge_dependency_errors_total` counts it |
| LLM summarizer | Extractive summary instead, `llm_summarizer_failed` warning |
| Postgres while recording a run | The caller still gets its optimized context; the lost row is logged and counted |
| Upstream (proxy) | 502 (unreachable) or 504 (timeout) with the upstream named; an upstream's own error status (for example TokenShield's 402) is returned unchanged. A stream that breaks half way ends, is logged and counted (`status="stream_error"`), and its connection returns to the pool |
| Object storage | Job creation fails with a clear error; synchronous optimization is unaffected |

## Deployment

Locally: Docker Compose with Floci for S3, KMS and Secrets Manager, provisioned by the same
Terraform modules as AWS (`make up`). On AWS: ECS Fargate (api, worker, web) behind an ALB
with WAF, RDS PostgreSQL, ElastiCache, S3, KMS, Secrets Manager and CloudWatch, from
`infra/terraform/envs/aws-dev` or `aws-prod`. See [deploy-aws.md](../guides/deploy-aws.md).

## Related documents

[LLD](LLD.md), [engine design](engine.md), [data model](data-model.md),
[security](security.md), [threat model](threat-model.md), [integrations](integrations.md),
[decision records](adr/).
