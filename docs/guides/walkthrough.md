# Code walkthrough

A guided tour for contributors: where things live, what happens to one optimize request,
and how to add the three things people most often want to add. The scope and design
rationale are in [docs/PLAN.md](../PLAN.md).

## Repository

```
apps/api/                 Python package: engine, context API, proxy, dashboard API, worker
  src/contextforge/       one package per domain (below)
  src/mockllm/            deterministic OpenAI-compatible upstream for demos and tests,
                          also answering as TokenShield-style and SmartRouter-style surfaces
  tests/unit, tests/integration
apps/web/                 Next.js dashboard (app/ routes, features/<domain>/, components/, lib/)
e2e/                      Playwright journeys
scripts/                  env generation, test-db, test matrix, tf-aws-on-floci, sanitization, qa/
infra/terraform/          modules and the local-floci, aws-dev, aws-prod environments
infra/docker/             api and web images
deploy/compose/           local stack (Floci overlay, real-AWS overlay)
docs/                     plan, guides, OpenAPI, benchmark results
```

## Package layout (`apps/api/src/contextforge`)

**`engine/` is pure.** No network, no database, no clock in the output except the measured
latency. It depends only on pydantic, tiktoken and orjson, and everything else depends on
it, never the other way round. `from contextforge import optimize` imports only this.

| Module | Role |
| --- | --- |
| `engine/types.py` | The public contract shared by the library and the HTTP API: `Message`, `Document`, `OptimizeOptions`, `OptimizeRequest`, `OptimizeResult`, `Stats`, `CitationEntry`, `Allocation`, `OptimizeWarning`, `TraceStep` |
| `engine/tokenizers.py` | `TokenizerRegistry`: model name to tokenizer (aliases, custom adapters, OpenAI rules, else a marked estimate `estimate:o200k_base*1.15`). Message framing per OpenAI's counting recipe |
| `engine/text.py` | Deterministic text analysis: blocks (code fences and JSON are atomic), sentences, search terms, critical facts (ids, paths, versions, numbers with units, config keys, error classes), shingles and Jaccard, importance |
| `engine/bm25.py` | BM25 relevance, normalized to 0..1 |
| `engine/toolout.py` | Tool output reduction: JSON reduced structurally and still valid, logs kept to their signal lines plus head and tail, source code never cut. Three levels (`LIGHT`, `NORMAL`, `HARD`) chosen by strategy |
| `engine/profiles.py` | Workload profiles (category weights plus ranking weights), `detect_workload`, and `allocate`, the water-filling budget split |
| `engine/summarizer.py` | The `Summarizer` protocol and `ExtractiveSummarizer`: copies sentences into Goals, Requirements and constraints, Decisions and conclusions, Key facts, Errors seen, Open questions |
| `engine/state.py` | Mutable working state for one run: `Work`, `MsgState`, `DocState`, `Unit` |
| `engine/stages.py` | Stages 3 to 5: `protect`, `clean`, `build_units`, `rank` |
| `engine/assemble.py` | Stage 6: `Assembler` fits units to the budget per category, rebuilds the message list in order, writes the summary into the room left, and repairs if the exact recount is over |
| `engine/validate.py` | Structure checks (tool call pairing) and citation checks |
| `engine/pipeline.py` | `optimize()`: runs the stages, times each into the trace, validates, escalates `balanced` to `aggressive` once, raises in strict mode |

Around the engine, packages follow router, service, repository/models layering:

| Package | Role |
| --- | --- |
| `context/` | `/v1/context/*` (optimize, count-tokens, summarize, rank, jobs). `ContextService` adds the result cache, run recording, metrics and the HTTP error mapping around the engine |
| `gateway/` | `/v1/chat/completions` and `/v1/models`: optimize, then forward to an upstream, streaming or not |
| `integrations/` | Upstream adapters (`openai`, `tokenshield`, `smartrouter`) and their registry |
| `upstreams/` | Named upstreams with sealed credentials; `resolve()` reads them through the config cache |
| `jobs/` | Background jobs: payloads in object storage, claim with `SKIP LOCKED` and leases |
| `runs/` | Append-only optimization runs, hourly rollups written in the same transaction, analytics |
| `profiles/` | Stored workload profiles merged over the built-ins (`table()`) |
| `keys/` | `cfk_` service keys and the `ServiceKey` dependency (auth plus per-key rate limit) |
| `benchmarks/` | Committed synthetic datasets, their seeded generator and the runner (`python -m contextforge.benchmarks`) |
| `benchmark_runs/` | Benchmark runs queued from the dashboard and executed by the worker |
| `llm/` | The optional `LLMSummarizer` over any OpenAI-compatible endpoint, with a fact guard and extractive fallback |
| `core/` | Settings and boot guards, database, KV store (Redis or memory), config cache, sealing (local AES-GCM or KMS), object storage (disk or S3), AWS clients, errors, logs, middleware, tracing, money |
| `demo/` | `seed-demo`: users, keys, upstreams, a custom profile, 60 days of replayed real engine results, a benchmark run and live traffic |
| `auth/`, `users/`, `audit/` | Dashboard sessions, CSRF and roles (`owner`, `admin`, `viewer`); users; the append-only audit log |
| `playground/`, `system/`, `observability/`, `limits/` | Dashboard playground; health, readiness, metrics and system info; Prometheus metrics; the sliding-window rate limiter |
| `migrations/` | Alembic environment and revisions (`contextforge migrate`) |
| `main.py`, `cli.py`, `worker.py` | App factory, the `contextforge` CLI, the worker loop. `bench.py` is `make bench`, `openapi.py` exports the spec |

Process-wide services (settings, database, KV, HTTP client, config cache, sealer, storage,
tokenizer registry) live in one `Container` (`core/container.py`), built in the app
lifespan and reached through `ContainerDep`, so tests build an isolated one per app.

## The life of an optimize request

`POST /v1/context/optimize` with a `cfk_` key:

1. **`core/middleware.py`** assigns the request id, adds security headers, and logs one
   line when the response is done.
2. **`context/router.py`** rejects bodies above `MAX_BODY_BYTES` (`body_limit`), and
   FastAPI validates the body as `OptimizeRequest` (`engine/types.py`). A bad body is a 422
   `validation_error`.
3. **`keys/dependencies.py service_key`** parses `cfk_<prefix>_<secret>`, loads the key
   through the config cache (5 s TTL, version stamp in the KV store), compares the peppered
   HMAC in constant time, checks revoked and expired, and takes one hit from the key's
   per-minute limit (`core/kv.py`, `limits/limiter.py` on Redis). A Redis failure here is
   counted and the request passes.
4. **`ContextService.optimize`** (`context/service.py`) loads the profile table
   (`profiles/service.table`), applies the key's default profile, and refuses an unknown
   one with `unknown_profile`.
5. It hashes the canonical request JSON with the config version and the LLM summarizer
   model into a result cache key. A hit returns the stored response with `cached: true`.
6. On a miss, `run_engine` calls `pipeline.optimize` in a worker thread with the
   container's tokenizer registry, the profile table and the chosen summarizer. In
   `engine/pipeline.py`:
   - **ingest**: resolve the tokenizer, build `Work`, flag input structure problems, pick
     the ranking query, detect the workload, pick the profile;
   - **measure**: count every message (with framing) and document;
   - **protect**: system and developer messages, the last N, pinned messages, the latest
     user turn, tool call pairs, documents cited by protected messages, `must_keep` holders;
   - **clean**: drop empties, exact duplicate messages and blocks (latest wins), near
     duplicates, duplicate documents (merged with a citation alias), reduce tool output;
   - **rank**: split into units and score each by relevance, recency and importance with
     the profile's weights; drop documents with no query overlap;
   - **compress**: `Assembler.run` allocates the budget across `history`, `tool`,
     `documents` and `summary`, keeps the best units (or extractive excerpts), summarises
     what was dropped, and repairs with an exact recount;
   - **validate**: build the citation map, recount, check structure, citations, required
     content and fact retention, and add warnings such as `budget_not_met`.
   If `balanced` missed the budget, the whole run is repeated as `aggressive`. With
   `on_budget_failure="error"` a miss raises, which the service maps to 422
   `budget_unsatisfiable`.
7. **`_response`** wraps the result as `OptimizeResponse` and adds `cost_avoided_usd`
   from `MODEL_PRICES` (`core/money.py`, amounts kept as integer nano-dollars). The
   response is cached unless it is larger than `RESULT_CACHE_MAX_BYTES`.
8. **`_observe`** updates the Prometheus metrics and logs `budget_not_met` events.
9. **`record`** writes the `OptimizationRun` and upserts its hourly rollup in one
   transaction (`runs/service.py`), plus the content to object storage when
   `STORE_CONTENT=true`. A failed write is logged and counted; the caller still gets its
   result.
10. The router sets `x-contextforge-cache` and `x-contextforge-run-id`.

The proxy (`gateway/router.py`) runs steps 3 to 8 with options built from headers and the
upstream's defaults, forwards the optimized body through the upstream's adapter, and
records the run with the upstream's model, status and cost. A job (`jobs/service.py`)
runs steps 4 to 9 in the worker, without the result cache.

## Add a tokenizer adapter

A tokenizer is any object with `id: str`, `exact: bool` and `count(text) -> int`
(the `Tokenizer` protocol in `engine/tokenizers.py`).

```python
from contextforge import TokenizerRegistry, optimize

class HFTokenizer:
    def __init__(self, tok, name):
        self._tok, self.id, self.exact = tok, name, True
    def count(self, text: str) -> int:
        return len(self._tok.encode(text).ids) if text else 0

registry = TokenizerRegistry()
registry.register(r"^llama-3", HFTokenizer(hf_tokenizer, "llama-3"))
result = optimize(request, registry=registry)
```

`register(pattern, tokenizer)` takes a regex matched against the lower-cased model name
after aliases are followed; custom adapters are checked before the OpenAI rules.

- **In the service:** the registry is built in `Container.build` (`core/container.py`) from
  `TOKENIZER_ALIASES`. Register the adapter there, after the registry is constructed.
- **A new OpenAI model family:** add a pattern to `_OPENAI_RULES`. A new tiktoken encoding
  also goes in `ENCODINGS`, so `warm_up()` loads it at boot and the API image caches it.
- **Tests:** a unit test in `tests/unit/engine/test_components.py` for resolution and
  exactness, and one in `tests/integration/test_context_api.py` if the service wiring
  changed. Keep `exact` honest: true only when counts come from the model's own tokenizer.

## Add a workload profile

Without code: create it on the dashboard's Profiles page or with
`POST /api/v1/profiles` (admin): a name, category `weights` (`history`, `tool`,
`documents`, `summary`, each 0 to 1, normalized at use), and ranking weights
(`relevance`, `recency`, `importance`). Requests select it with `options.profile`, keys
with a default profile, the proxy with `x-contextforge-profile`. Saving bumps the config
version, so cached results never mix old and new weights.

As a built-in:

1. Add a `Profile(...)` to `BUILTIN_PROFILES` in `engine/profiles.py`.
2. If it should be a selectable and detectable workload, add its name to `Workload` and
   `ResolvedWorkload` in `engine/types.py`, teach `detect_workload` when to pick it, and add
   it to `WORKLOADS` in `apps/web/src/lib/chips.ts`.
3. Cover detection and allocation in `tests/unit/engine/test_components.py`, then run
   `make openapi` and `pnpm gen:api` in `apps/web`.

## Add an upstream kind

1. Create `integrations/<kind>.py` with a class that has `kind`, `passthrough_prefixes`
   (client request headers forwarded, by lower-case prefix), `expose_prefixes` (upstream
   response headers returned) and `report(headers, body) -> UpstreamReport` (the model
   actually used, and the cost in nano-dollars via `header_cost`). See `tokenshield.py`
   and `smartrouter.py`.
2. Register it in `ADAPTERS` in `integrations/registry.py`. Unknown kinds fall back to the
   plain `openai` adapter.
3. Add the kind to `Kind` in `upstreams/schemas.py` (the column holds at most 16
   characters) and to the kind options in
   `apps/web/src/features/upstreams/components/upstreams-screen.tsx` (and a chip in
   `lib/chips.ts`).
4. If its model is chosen after the call (like SmartRouter's `auto`), make sure that
   model name resolves to the estimate, not to a wrong exact tokenizer.
5. Add a surface for it to `src/mockllm/app.py` that follows its documented contract, and
   contract tests to `tests/integration/test_integrations.py`. Run `make openapi` and
   `pnpm gen:api`.

## Add an admin endpoint

Domain `router.py` (HTTP only, role dependency `Viewer`, `Admin` or `Owner`),
`schemas.py`, `service.py` (rules plus `audit(...)` in the same transaction), and, if it
changes what `/v1` reads (keys, profiles, upstreams), `await
container.config_cache.invalidate()` after the write. Run `make openapi` and
`pnpm gen:api` in `apps/web` to refresh the typed client.
