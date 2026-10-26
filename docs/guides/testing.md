# Testing

ContextForge has several layers of automated checks. Each proves something different. The
current test counts are in the README's Testing table; this guide describes what each
layer covers and how to run it.

| Layer | Command | Needs | Proves |
| --- | --- | --- | --- |
| Static | `make lint typecheck` | uv, pnpm | ruff (lint and format), mypy `--strict`, ESLint and TypeScript strict across the API and the dashboard |
| Unit | `make test` | uv, pnpm | Pure logic: the engine, core primitives, benchmarks and the OpenAPI drift check (pytest), and dashboard logic and components (Vitest) |
| Integration | `make test-integration` | Docker | The real API in-process against real Postgres and Redis, with the mock LLM over real HTTP |
| Option matrix (8 runs) | `make test-matrix` | `make up` (Floci) | The integration suite under every cache, key and storage backend |
| Browser e2e | `make e2e` | `make up && make demo` | User journeys through the real dashboard, API, proxy and mock LLM |
| Browser QA | `make qa` | `make up && make demo` | Every page in light and dark, desktop and phone, with no console errors, failed requests, broken images, error states or overflow |
| Quality benchmark | `make benchmark` | uv | Token reduction and fact retention on the committed datasets, against truncation at the same budget |
| Service benchmark | `make bench` | `make up && make demo` | Latency and throughput of the running stack |
| Infrastructure | `make tf-validate tf-lint tf-security` | Docker | Terraform validity for three environments, tflint and checkov |
| AWS on Floci | `make tf-aws-on-floci` | Docker | The full `aws-dev` environment plans, applies, converges and destroys against an AWS API |
| Sanitization | `make sanitize` | bash | No secrets, cloud identifiers, committed env files or em/en dashes in the tree |

## Unit tests

```bash
make test
```

Runs `uv run pytest tests/unit -q` in `apps/api` and `pnpm test` (Vitest) in `apps/web`.
No database and no network.

| Location | Covers |
| --- | --- |
| `apps/api/tests/unit/engine/` | `test_pipeline.py`: every pipeline guarantee (fits the budget with an exact recount, system messages byte for byte, recent turns untouched, tool call pairs, required content, strict mode, offline operation for acceptance criterion 1). `test_components.py`: tokenizers and exactness, block and sentence splitting, critical facts, deduplication, tool output reduction (JSON stays valid), BM25, budget allocation, workload detection, summaries, structure validation |
| `apps/api/tests/unit/core/` | Config and the production boot guards, the KV store and config cache, money conversion, schemas, logs and errors, sealing and storage, security primitives |
| `apps/api/tests/unit/benchmarks/` | The committed dataset matches its seeded generator, the simulated reader is deterministic, and acceptance criterion 13 (ContextForge beats truncation at the same budget) |
| `apps/api/tests/unit/system/test_openapi_drift.py` | Fails if `docs/api/openapi.yaml` no longer matches the app. `make openapi` regenerates it |
| `apps/api/tests/unit/jobs/test_worker_models.py` | A bare worker process registers every table mapper before it writes |
| `apps/web/test/` | Formatting, error messages, domain helpers and components (Vitest) |

## Integration tests

```bash
make test-integration
```

`scripts/test-db.sh` reuses the Compose Postgres and Redis when they are up, and otherwise
starts just those two. The suite then runs `apps/api/tests/integration` against
`contextforge_test` (created fresh for the session and migrated with Alembic) and Redis
database 15, with coverage. The mock LLM runs in a background thread on a free port.

Safety: the suite truncates every table, so it refuses a database whose name lacks `test`,
and any host other than `localhost`, `127.0.0.1` or `postgres` unless
`ALLOW_REMOTE_TEST_DB=true`. Override the targets with `TEST_DATABASE_URL` and
`TEST_REDIS_URL`.

| File | Proves |
| --- | --- |
| `test_context_api.py` | Acceptance criteria 2 to 10 over HTTP: budgets met with exact counts, exact and estimated tokenizers, structured `unsupported_tokenizer`, deduplication that keeps structure, system and recent messages preserved, structured summaries keep facts, RAG citations mapped, real stats, `budget_not_met`, strict mode, required content, untrusted content treated as data; plus the result cache, profile invalidation, key default profiles, validation and payload limits |
| `test_gateway.py` | Acceptance criterion 11: an unmodified OpenAI SDK, streaming and not; budget headers and `optimize: off`; upstream errors; unknown and disabled upstreams; bad bodies; `/v1/models` |
| `test_integrations.py` | Acceptance criterion 12: TokenShield cost and headers recorded, its 402 passed through; SmartRouter `auto` estimated and the routed model recorded; adapters optional. Contract tests against simulated upstreams |
| `test_jobs.py` | Acceptance criterion 14: the job lifecycle with payloads in object storage, key scoping, failure reporting, concurrent workers never double-claim, expired leases reclaimed |
| `test_analytics.py` | Acceptance criterion 15: runs, rollups and the overview agree; runs are append-only; content stored only when enabled; benchmark runs from the dashboard |
| `test_admin.py` | Sign-in and lockout, CSRF, roles, service key lifecycle, per-key rate limits, sealed upstream credentials, profiles, owner guards, append-only audit log, health, system info, playground |
| `test_reliability.py` | Redis down still optimizes; the LLM summarizer down, unconfigured or in use; concurrent optimizations all recorded |
| `test_backends.py` | The configured storage and key backends are the ones actually used (round trips through each) |
| `test_hardening.py` | Hostile and racy input: deeply nested tool JSON and lone surrogates are not 500s, engine saturation answers 503 with `Retry-After` and slots are released, `/rank` stays fast at 3,000 passages, malformed key prefixes and upstream names never reach the cache, an upstream cannot be moved to another host with its stored key, forged `X-Forwarded-For` cannot dodge the login throttle, parallel wrong passwords still lock, sign-out ends the session server-side, two owners demoting each other keep an owner, parallel benchmark requests queue one, a worker that lost its lease cannot overwrite the result, a job that keeps killing workers fails, rollups group unknown models, gzip streams are decoded, a racing user create is a 409 with no hash in the logs, a signed-out session survives cache eviction, chunked bodies obey the limit, proxy validation errors are 422, expired run content is 410, every CPU endpoint respects the engine slots, key defaults must exist and stay referenced, upstreams cannot target instance metadata |
| `test_tracing.py` | OpenTelemetry spans for optimize, its stages and the proxy upstream call |

## Option matrix

```bash
make up
make test-matrix
```

`scripts/test-matrix.sh` checks that Floci answers on `localhost:4366`, then runs the
integration suite eight times, once per combination:

| Axis | Values | Set by |
| --- | --- | --- |
| Cache | `redis`, `memory` (no Redis at all) | `TEST_CACHE` |
| Keys | `local` (AES-GCM), `kms` (Floci KMS) | `TEST_KEY_MODE` |
| Storage | `local` (disk), `s3` (Floci S3) | `TEST_STORAGE` |

The `memory` leg is acceptance criterion 1: the service passes the whole suite with Redis
disabled. The script prints the failing combinations, or `matrix: all 8 combinations
passed`.

## Browser end-to-end tests

```bash
make up && make demo
make e2e
```

Playwright (Chromium) against http://localhost:4310 (`WEB_URL` to change it), signed in
with `CF_DEMO_PASSWORD` from `deploy/compose/.env`. The suites share the demo database, so
they run in one worker, in file order:

| Suite | Journey |
| --- | --- |
| `e2e/tests/01-auth.spec.ts` | A wrong password is explained, the right one lands on the overview; protected pages redirect to sign in and back to where you were; a crafted `next=` cannot leave the site; signing out ends the session for good |
| `e2e/tests/02-playground.spec.ts` | A coding agent trace keeps every fact; a noisy retrieval keeps every citation resolvable; input that is not JSON is caught before the request |
| `e2e/tests/03-runs-and-analytics.spec.ts` | The overview shows savings and fact retention; a run opens with its trace and allocation; filters; the demo's background jobs succeeded |
| `e2e/tests/04-keys-and-api.spec.ts` | A key created in the dashboard optimizes over the API until it is revoked |
| `e2e/tests/05-profiles-upstreams.spec.ts` | Editing a profile changes how the budget is split; an upstream added in the dashboard serves the proxy |
| `e2e/tests/06-benchmarks-and-roles.spec.ts` | A benchmark run from the dashboard beats truncation; a viewer reads everything and changes nothing |
| `e2e/tests/07-people-and-account.spec.ts` | An owner adds a user, changes the role and name, and disabling stops sign-in (with the audit log filtered to the changes); a password change works with the new password only; a viewer has no Users or Audit pages and no write buttons; the theme switches and sticks |
| `e2e/tests/08-configuration.spec.ts` | A custom profile is created, used over the API and deleted; a key is edited in place (name, limit, expiry); an upstream is edited and a host change asks for its key again; integrations show snippets for this install; a finished benchmark's report downloads as Markdown |

`E2E_HEADED=1` (inside `e2e/`, with `pnpm test`) shows the browser. Failures keep a trace
and a screenshot in `e2e/test-results`; the HTML report is in `e2e/playwright-report`.

## Browser QA

```bash
make qa
```

`scripts/qa/qa.mjs` (Puppeteer) signs in through the real form, visits every dashboard page
in light and dark at desktop and phone width, saves screenshots to `scripts/qa/output`,
and fails on console errors, failed or 4xx/5xx requests, broken images, error states and
horizontal overflow. `QA_PAGES`, `QA_THEMES` and `QA_SIZES` narrow a run; `QA_BASE` changes
the target.

## Benchmarks

```bash
make benchmark    # quality: writes docs/benchmarks/results.md and results.json
make bench        # service: latency and throughput against the running stack
```

`make benchmark` runs every method (ContextForge strategies, truncation and no-op
baselines) on the committed synthetic datasets, five runs each, and needs no services.
`make bench` measures count-tokens, cold and warm optimize, the proxy's overhead over a
direct upstream call, and concurrent throughput, over HTTP against the production images.
Its numbers depend on the machine.

## Infrastructure

```bash
make tf-validate      # terraform validate for local-floci, aws-dev and aws-prod
make tf-lint          # tflint, plugins cached in a docker volume
make tf-security      # checkov
make tf-aws-on-floci  # the real aws-dev configuration against a throwaway Floci
```

`tf-validate` uses a local `terraform` when installed and the pinned
`hashicorp/terraform:1.16.6` image otherwise. `tf-aws-on-floci` starts a separate Floci on
port 4396 (container `contextforge-tf-floci`), copies the Terraform tree to a temp
directory, then plans, applies, re-plans and destroys `aws-dev`. The repository is not
touched. A few attributes Floci does not persist show up as expected re-plan drift. It
takes about five minutes.

## Sanitization

```bash
make sanitize
```

`scripts/check-sanitization.sh` scans every file git would commit for cloud credentials,
private keys, account and resource ids, committed env files, and the em and en dash
characters. Run it before every commit.
