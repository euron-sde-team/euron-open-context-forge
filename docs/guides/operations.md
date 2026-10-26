# Operations

## Processes

Everything except the dashboard runs from one image and one CLI, `contextforge`.

| Process | Command | Scale |
| --- | --- | --- |
| API and proxy | `contextforge serve` | Stateless; run as many replicas as traffic needs. Flags `--host`, `--port` (default `$PORT`, else 4330) and `--workers` (default `$WEB_CONCURRENCY`, else 1: scale with replicas so metrics stay exact). 30 s graceful drain; ECS waits 45 s before SIGKILL |
| Worker | `contextforge worker` | Background jobs and benchmark runs. Any number of replicas; work is claimed with `FOR UPDATE SKIP LOCKED`, so two workers never take the same item |
| Dashboard | Next.js standalone server | Stateless. Locally it proxies `/api/*`, `/v1/*`, `/health`, `/healthz`, `/readyz`, `/docs` and `/openapi.json` to the API (`API_INTERNAL_URL`, fixed at image build), so the browser talks to one origin. On AWS the load balancer routes those paths to the API before they reach the dashboard |
| Migrations | `contextforge migrate` | One-off before each release (Compose: the `migrate` service; ECS: the `migrate` task) |

Other commands: `contextforge create-owner`, `contextforge seed-demo` (refused in
production), `contextforge benchmark`, `contextforge openapi`.

## Health

| Endpoint | Meaning |
| --- | --- |
| `GET /healthz` | Liveness: the process answers. Used by the container health checks and the ALB target group |
| `GET /health` | Same, plus the version |
| `GET /readyz` | Readiness. Probes Postgres, and Redis when `REDIS_URL` is set, each with a 2 s timeout |
| `GET /api/v1/system` | Deployment configuration and live checks (dashboard Settings page, any signed-in role) |

Redis is optional, so readiness depends on Postgres only:

| Postgres | Redis | HTTP | `status` |
| --- | --- | --- | --- |
| ok | ok or not configured | 200 | `ready` |
| ok | down | 200 | `degraded` |
| down | any | 503 | `degraded` |

The body has `checks` with `ok` and `ms` (or `error`) per dependency. While Redis is down,
optimization keeps working: cache lookups count as misses, rate limits are not enforced,
and the config cache falls back to its 5 s TTL. Each absorbed failure increments
`contextforge_dependency_errors_total`.

## Metrics

`GET /metrics` exposes Prometheus metrics (`apps/api/src/contextforge/observability/metrics.py`).
Labels are bounded sets, never per-request values. Behind the AWS load balancer it answers
only to `metrics_allowed_cidrs`.

| Metric | Type | Labels | Use |
| --- | --- | --- | --- |
| `contextforge_optimizations_total` | counter | `source`, `workload`, `strategy`, `budget_met` | Traffic by source (`api`, `proxy`, `job`, `playground`) and outcome |
| `contextforge_tokens_in_total` | counter | `source` | Tokens received |
| `contextforge_tokens_out_total` | counter | `source` | Tokens returned after optimization |
| `contextforge_optimize_seconds` | histogram | `source` | Engine time per optimization |
| `contextforge_stage_seconds` | histogram | `stage` | Engine time per pipeline stage (cache misses only) |
| `contextforge_reduction_ratio` | histogram | | Share of input tokens removed |
| `contextforge_fact_retention_ratio` | histogram | | Share of critical facts retained |
| `contextforge_result_cache_total` | counter | `result` (`hit`, `miss`) | Result cache effectiveness |
| `contextforge_warnings_total` | counter | `code` | Warnings returned, e.g. `budget_not_met`, `llm_summarizer_failed` |
| `contextforge_dependency_errors_total` | counter | `dependency`, `operation` | Absorbed failures of Redis (`cache_get`, `cache_set`, `rate_limit`) and Postgres (`record_run`) |
| `contextforge_upstream_requests_total` | counter | `upstream`, `kind`, `status` | Proxied calls by status class (`2xx`, `4xx`, ...), `timeout` or `unreachable` |
| `contextforge_upstream_seconds` | histogram | `upstream` | Upstream latency to headers |
| `contextforge_jobs_total` | counter | `status` | Jobs by final status (`succeeded`, `failed`) |

Useful alerts: `rate(contextforge_warnings_total{code="budget_not_met"}[5m])` above
normal (budgets set below what protected content needs), any growth in
`contextforge_dependency_errors_total`, `contextforge_upstream_requests_total` with
`status="timeout"` or `"unreachable"`, and the p95 of `contextforge_optimize_seconds`.

## Logs

Logs are JSON lines on stdout with `ts`, `level`, `logger`, `msg` and `request_id`. The
request id is taken from an incoming `x-request-id` (up to 64 letters, digits, `-` and `_`)
or generated, and returned as `x-request-id` on every response. Each request writes one
`request` line with `method`, `path`, `status` and `ms` (not for `/healthz`, `/readyz` and
`/metrics`). Fields named like credentials (`authorization`, `api_key`, `password`,
`secret`, `token`, `x-api-key`) are written as `[redacted]`.

Every optimization that misses its budget writes one line with
`"event": "budget_not_met"`, the `source`, the `budget` and the `optimized_tokens`. On
AWS the observability module turns these into a CloudWatch metric through a log metric
filter (the module variable `budget_missed_log_pattern`, which must match
`{ $.event = "budget_not_met" }`) and alarms when `budget_missed_threshold` is set.

Log lines carry no message or document content, and runs keep only stats, warnings and
the trace unless `STORE_CONTENT=true`. Traces: set `OTEL_ENABLED=true` and the standard
`OTEL_EXPORTER_OTLP_ENDPOINT`.

## Worker

The worker loops: each tick processes at most one optimization job and one benchmark run,
and when there was nothing to do it waits `JOB_POLL_INTERVAL_S`. SIGTERM finishes the item
in hand, then exits.

- **Jobs.** `POST /v1/context/jobs` writes the payload to object storage
  (`jobs/<id>/payload.json`) and a `queued` row. A worker claims the oldest queued job, or a
  `running` job whose lease has expired, with `FOR UPDATE SKIP LOCKED`, sets a lease of
  `JOB_LEASE_S` and runs the engine (without the result cache). The result goes to
  `jobs/<id>/result.json` and the run is recorded with source `job`. A deterministic
  refusal (`unsupported_tokenizer`, `budget_unsatisfiable`, `unknown_profile`) fails the
  job at once; any other error requeues it, and the third failed attempt marks it `failed`
  with `job_error`.
- **Benchmark runs.** Queued from the dashboard's Benchmarks page (one at a time), claimed
  with `SKIP LOCKED`, run on the committed datasets, and stored with a markdown report at
  `benchmarks/<id>/report.md`.

With no worker running, jobs and benchmark runs stay `queued`; everything else works.

## Creating an owner

The first owner of a fresh install is created from the CLI:

```bash
# Local stack
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml \
  -f deploy/compose/compose.floci.yaml exec api contextforge create-owner --email you@example.com

# Anywhere else, non-interactively
CONTEXTFORGE_OWNER_PASSWORD='<strong password>' contextforge create-owner --email you@example.com --name "Your Name"
```

Without `CONTEXTFORGE_OWNER_PASSWORD` it prompts for the password. The password policy is
enforced. If the email already exists, the user is made owner, the password is reset, the
account is re-enabled and its existing sessions end. On ECS, run it as a command override
of the `migrate` task (see [deploy-aws.md](deploy-aws.md)).

## Routine tasks

- **Rotate an upstream credential:** Upstreams, edit, paste the new key. It is sealed
  before it is stored and is live on every instance within the config cache's 5 s TTL
  (about a second with shared Redis, which carries the version stamp).
- **Rotate a service key:** create a new key on the API keys page, deploy it to the
  application, revoke the old one. Revocation reaches other instances the same way.
- **Change a workload profile:** Profiles, edit the weights. The change bumps the config
  version, which is part of the result cache key, so cached results from the old weights
  are never served. A built-in profile can be reset to its defaults.
- **Change prices:** set `MODEL_PRICES` and restart. Prices only feed the
  `cost_avoided_usd` estimate.
- **Rotate `SESSION_SECRET`:** signs everyone out.
- **Rotate `API_KEY_PEPPER`:** invalidates every service key; issue new keys first.
- **Change `LOCAL_MASTER_KEY`:** stored upstream credentials can no longer be opened.
  There is no re-seal command in 0.1.0, so re-enter each upstream's key afterwards. With
  `KEY_MODE=kms`, KMS rotates the key material itself (the `kms` module enables yearly
  rotation) and old ciphertexts stay readable.

## Backups

Postgres holds everything durable: users, service keys, profiles, upstreams (sealed
credentials), runs and their hourly rollups, job and benchmark rows, and the append-only
audit log. RDS automated backups cover it (3 days in `aws-dev`, 14 in `aws-prod`).

Object storage holds working data: job payloads and results, benchmark reports and, with
`STORE_CONTENT=true`, run content. On AWS the payloads bucket expires objects after 30
days, so collect job results within that window. Redis holds only recomputable state
(result cache, rate-limit windows, the config version stamp) and needs no backup.

Keep `LOCAL_MASTER_KEY` (or the KMS key) as safe as the database: a database restore
without it cannot open the upstream credentials.

## Scaling notes

- The engine is CPU bound. It runs in a worker thread so it never blocks the event loop;
  throughput grows with `--workers` processes per task and with replicas. `make bench`
  measures it on your hardware.
- With more than one API process, set `REDIS_URL`. Without it each process keeps its own
  result cache, config version and rate-limit windows, so a key's RPM limit applies per
  process and invalidation relies on the 5 s TTL.
- Each process opens up to `DB_POOL_SIZE + DB_MAX_OVERFLOW` connections (30 by default).
  Size the total (processes times that) under the database's connection limit.
- Very large inputs belong in background jobs: they do not hold a request open and their
  payloads never pass through Postgres. `MAX_BODY_BYTES` caps request bodies.
- Near-duplicate detection between documents is pairwise; beyond 400 documents in one
  request only exact duplicates are merged.
