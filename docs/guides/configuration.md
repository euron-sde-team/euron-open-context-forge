# Configuration reference

Every setting is an environment variable, read once at boot by
`apps/api/src/contextforge/core/config.py` (pydantic settings, case-insensitive). The
variable name is the upper-case field name, with one exception: the cloud mode is read
only from `CONTEXTFORGE_CLOUD`. The API, the worker and every CLI command share these
settings.

## Production boot guards

With `ENVIRONMENT=production`, `Settings.guard()` refuses to start and lists every problem
it finds:

- `SESSION_SECRET` and `API_KEY_PEPPER` must each be at least 32 characters, must not be a
  known placeholder (`change-me`, `dev`, `secret`, `replace-with-output-of-make-env`, empty)
  and must not contain `not-for-production` (the development defaults do).
- `SESSION_SECRET` and `API_KEY_PEPPER` must differ.
- With `KEY_MODE=local`, `LOCAL_MASTER_KEY` must be at least 32 characters and not the
  development default. Or use `KEY_MODE=kms`.
- With `CONTEXTFORGE_CLOUD=aws`, `AWS_ENDPOINT_URL` must be unset.
- `AUTH_REQUIRED=false` is refused.
- `COOKIE_SECURE` must be `true`.

In `development` and `test` none of these checks run, which is why the local stack can use
an emulator endpoint and plain HTTP cookies. `contextforge seed-demo` also refuses to run
with `ENVIRONMENT=production`.

## Runtime

| Variable | Default | Meaning |
| --- | --- | --- |
| `ENVIRONMENT` | `development` | `development`, `test` or `production`. Production enables the boot guards and blocks the demo seed |
| `CONTEXTFORGE_CLOUD` | `local` | `local`, `floci` or `aws`: where the AWS services live. Reported on the Settings page; on `aws` the guard refuses an `AWS_ENDPOINT_URL` override |
| `LOG_LEVEL` | `INFO` | Level of the JSON logs on stdout |

## Data stores

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://contextforge:contextforge@localhost:4342/contextforge` | Postgres 16 (no extensions needed) |
| `DB_POOL_SIZE` | `10` | SQLAlchemy connection pool size per process |
| `DB_MAX_OVERFLOW` | `20` | Extra connections allowed above the pool size under load |
| `REDIS_URL` | empty | Redis 7 or Valkey. Empty means no Redis: the result cache, per-key rate limits and the config version stamp run in process. That is exact for one replica; set it when you run several |

## Security

| Variable | Default | Meaning |
| --- | --- | --- |
| `SESSION_SECRET` | development value | Signs dashboard sessions. 32+ random characters in production |
| `API_KEY_PEPPER` | development value | HMAC pepper for `cfk_` service key hashes. 32+ random characters, different from `SESSION_SECRET`. Changing it invalidates every service key |
| `SESSION_TTL_HOURS` | `12` | Dashboard session lifetime |
| `COOKIE_SECURE` | `false` | Mark the session cookie Secure. Must be `true` in production (behind HTTPS) |
| `CORS_ORIGINS` | `http://localhost:4310` | Comma-separated browser origins allowed to call the API directly |
| `KEY_MODE` | `local` | How upstream credentials are sealed before they reach the database: `local` (AES-GCM with `LOCAL_MASTER_KEY`) or `kms` |
| `LOCAL_MASTER_KEY` | development value | Key material for `KEY_MODE=local`. 32+ characters in production. Changing it makes stored upstream keys unreadable |
| `KMS_KEY_ID` | `alias/contextforge-local` | KMS key id or alias for `KEY_MODE=kms`. Every seal carries the encryption context `contextforge:record=<upstream id>` |

## AWS and object storage

| Variable | Default | Meaning |
| --- | --- | --- |
| `AWS_REGION` | `us-east-1` | Region for S3 and KMS |
| `AWS_ENDPOINT_URL` | unset | Endpoint override for an emulator (Floci). Must be unset on real AWS |
| `S3_FORCE_PATH_STYLE` | `false` | Path-style S3 addressing (needed for Floci) |
| `STORAGE` | `local` | Where payloads go: `local` (disk) or `s3` |
| `PAYLOADS_BUCKET` | `contextforge-local-payloads` | S3 bucket for job payloads and results, benchmark reports and stored run content. Objects are written with SSE-KMS |
| `LOCAL_STORAGE_DIR` | `./.data/payloads` | Directory for `STORAGE=local` (`/data/payloads` in Compose, a volume shared by api and worker) |

## Service behaviour

| Variable | Default | Meaning |
| --- | --- | --- |
| `AUTH_REQUIRED` | `true` | Require a `cfk_` service key on `/v1`. With `false`, requests without a key run as `anonymous` with `DEFAULT_RPM_LIMIT`. Turn off only on a private network; refused in production |
| `DEFAULT_RPM_LIMIT` | `600` | Requests per minute for a key that has no limit of its own |
| `RESULT_CACHE_TTL_S` | `600` | How long an optimize response stays in the result cache |
| `RESULT_CACHE_MAX_BYTES` | `2000000` | Responses larger than this are not cached |
| `MEMORY_CACHE_MAX_BYTES` | `64000000` | Without Redis: total size of the in-process cache (results evicted oldest first) |
| `MAX_BODY_BYTES` | `32000000` | Largest request body `/v1/context/*` accepts (413 `payload_too_large` above it) |
| `ENGINE_CONCURRENCY` | `4` | Optimizations running at once per process (the engine is CPU bound). Further requests wait for a slot |
| `ENGINE_QUEUE_TIMEOUT_S` | `10` | How long a request waits for an engine slot before it gets 503 `engine_busy` with `Retry-After` |
| `STORE_CONTENT` | `false` | Keep each run's request and response in object storage (`runs/YYYY/MM/DD/<uuid>.json`) so the dashboard can show them. Off: runs keep stats, warnings and the trace only |
| `TOKENIZER_ALIASES` | empty | `alias=target` pairs, comma separated. The target is an encoding (`o200k_base`, `cl100k_base`) or another model name. Example: `chat-small=gpt-4o-mini,chat-large=gpt-4o` (the Compose default, matching TokenShield's demo aliases) |
| `MODEL_PRICES` | built-in table | `model=usd_per_million_input_tokens` pairs, comma separated, merged over the defaults. Used only for the `cost_avoided_usd` estimate. Unknown models report no estimate; a dated name such as `gpt-4o-2024-08-06` matches its longest known prefix |

The built-in price table (USD per 1M input tokens, list prices, an estimate only):
`gpt-4o` 2.50, `gpt-4o-mini` 0.15, `gpt-4.1` 2.00, `gpt-4.1-mini` 0.40, `gpt-4.1-nano`
0.10, `o3` 2.00, `o4-mini` 1.10, `claude-sonnet-4-5` 3.00, `claude-haiku-4-5` 1.00.

## Proxy (`/v1/chat/completions`)

| Variable | Default | Meaning |
| --- | --- | --- |
| `UPSTREAM_TIMEOUT_S` | `120` | Timeout of the shared HTTP client used for upstream calls (connect timeout 5 s) |
| `DEFAULT_UPSTREAM` | unset | Upstream name used when neither the request header nor the key names one. Unset: the first enabled upstream |
| `DEFAULT_PROXY_STRATEGY` | `balanced` | Strategy when neither the header nor the upstream sets one |

## Optional LLM summarizer

Used only when a request asks for `"summarizer": "llm"`. Any OpenAI-compatible endpoint
works, including TokenShield or SmartRouter.

| Variable | Default | Meaning |
| --- | --- | --- |
| `LLM_SUMMARIZER_URL` | unset | Base URL, e.g. `https://host/v1`. Unset: the extractive summarizer is used, and a response that needed a summary carries the warning `llm_summarizer_failed` |
| `LLM_SUMMARIZER_MODEL` | `gpt-4o-mini` | Model name sent to the endpoint (also part of the result cache key) |
| `LLM_SUMMARIZER_API_KEY` | unset | Sent as `Authorization: Bearer` |
| `LLM_TIMEOUT_S` | `20` | Hard timeout per summary call; on timeout the extractive summarizer stands in |
| (fixed) | 2 calls, 200,000 chars | Per request, the LLM summarizer is called at most twice and sees at most 200,000 characters of transcript; past that the extractive summarizer stands in |

## Jobs

| Variable | Default | Meaning |
| --- | --- | --- |
| `JOB_POLL_INTERVAL_S` | `1.0` | How long an idle worker waits before looking for work again |
| `JOB_LEASE_S` | `300` | Lease on a claimed job, renewed by the worker every third of it while the job runs. A job whose worker died is claimed again after its lease expires; a worker that lost its lease cannot overwrite the result. After three attempts the job fails (`job_abandoned` when the worker kept dying) |
| `WORKER_METRICS_PORT` | `9464` | Port the worker serves Prometheus `/metrics` on (job counters, job-side optimize metrics). `0` turns it off |

## Observability

| Variable | Default | Meaning |
| --- | --- | --- |
| `OTEL_ENABLED` | `false` | Export OpenTelemetry traces over OTLP/HTTP, configured by the standard `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_SERVICE_NAME` |
| `WEB_CONCURRENCY` | `1` | uvicorn processes per API container. Keep 1 and scale with containers: `/metrics`, rate limits without Redis and the config cache are then exact |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxies whose `X-Forwarded-For` is trusted (comma separated, CIDRs allowed). On AWS the VPC CIDR; Compose sets `*` for the dashboard container. Drives the login throttle and audit IPs |

## Request options (`options` in an optimize request)

These come from `OptimizeOptions` in `apps/api/src/contextforge/engine/types.py`. They
are the same in the Python library, `/v1/context/optimize`, `/v1/context/jobs` and the
playground. Unknown fields are rejected.

| Option | Default | Meaning |
| --- | --- | --- |
| `max_input_tokens` | none | Budget for messages plus documents (1 to 10,000,000). Omit it to clean only: deduplication and tool output reduction, no budget |
| `reserve_output_tokens` | `0` | Room kept free for the answer. The effective budget is `max_input_tokens - reserve_output_tokens` |
| `strategy` | `balanced` | `conservative` removes only duplicates and tool output bulk; `balanced` ranks, compresses and summarises; `aggressive` squeezes harder (lower near-duplicate threshold, harder tool output reduction and, when over budget, protected tool results too). A `balanced` run that misses the budget is retried once as `aggressive` (warning `strategy_escalated`) |
| `workload` | `auto` | Budget profile: `coding`, `research`, `support`, `agent`, `rag`, `chat`, or `auto` to detect it from the input |
| `profile` | none | Name of a stored profile (service only; the library uses the table you pass). Overrides the workload weights. The service returns 400 `unknown_profile` for a name it does not know |
| `preserve_recent_messages` | `4` | The last N messages are never rewritten |
| `preserve_system_instructions` | `true` | System and developer messages are always returned verbatim; with `false`, exact duplicates among them may be removed |
| `pin_messages` | `[]` | Message indexes never rewritten (must be inside the message list) |
| `must_keep` | `[]` | Strings that must survive verbatim (up to 200, each up to 2,000 characters). A string that cannot be kept produces `required_content_missing` |
| `deduplicate` | `true` | Remove exact duplicate messages and paragraphs (latest wins) and near-duplicate blocks |
| `summarize_history` | `true` | Fold dropped history into one structured summary message |
| `reduce_tool_output` | `true` | Shrink long tool results (JSON structurally, logs to their signal lines) |
| `rank_documents` | `true` | Rank documents against the query |
| `drop_irrelevant_documents` | `true` | With ranking on, drop documents with no term overlap with the query (not in `conservative`) |
| `max_documents` | none | Keep at most this many documents (cited and required ones count first) |
| `query` | latest user turn | Ranking query. A terse last turn borrows the previous user turn's terms |
| `summary_role` | `user` | Role of the summary message: `user`, `assistant` or `system`. `system` produces the warning `summary_in_system_role`, because the summary quotes untrusted text |
| `summarizer` | `extractive` | `extractive` (deterministic) or `llm` (needs `LLM_SUMMARIZER_URL` on the service) |
| `on_budget_failure` | `warn` | `warn` returns the best safe result with `budget_met: false`; `error` returns 422 `budget_unsatisfiable` |
| `allow_estimate` | `true` | Allow a marked estimate when the model has no known tokenizer; `false` returns 422 `unsupported_tokenizer` instead |
| `include_trace` | `true` | Return the per-stage trace |

Request limits: `model` up to 200 characters; up to 20,000 messages and 20,000
documents; at least one message or document; document ids unique (1 to 200 characters).

## Proxy request headers

From the docstring of `apps/api/src/contextforge/gateway/router.py`:

| Header | Meaning |
| --- | --- |
| `x-contextforge-upstream` | Upstream name. Default: the key's default upstream, then `DEFAULT_UPSTREAM`, then the first enabled upstream |
| `x-contextforge-max-input-tokens` | Budget for this call (a positive integer). Default: the upstream's `max_input_tokens` |
| `x-contextforge-strategy` | `conservative`, `balanced` or `aggressive`. Default: the upstream's strategy |
| `x-contextforge-profile` | A workload profile name. Default: the key's default profile |
| `x-contextforge-optimize: off` | Forward untouched (still authenticated and logged) |

When the request sets `max_completion_tokens` or `max_tokens` below the budget, that amount
is reserved for the answer.

Response headers: `x-contextforge-original-tokens`, `x-contextforge-optimized-tokens`,
`x-contextforge-reduction-percent`, `x-contextforge-tokenizer`, `x-contextforge-exact`,
`x-contextforge-budget-met`, `x-contextforge-run-id`, `x-contextforge-cache`, and
`x-contextforge-warnings` (warning codes, comma separated) when there are any, plus the
upstream's own headers for its kind (see [integrate.md](integrate.md#upstream-kinds)).

## Compose variables

The local stack reads `deploy/compose/.env` (written by `make env`): `SESSION_SECRET`,
`API_KEY_PEPPER`, `LOCAL_MASTER_KEY`, `CF_DEMO_PASSWORD`, and the optional port and log
overrides listed in [quickstart-local.md](quickstart-local.md#start).
