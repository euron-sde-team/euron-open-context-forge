# Troubleshooting

## Local stack

| Symptom | Cause | Fix |
| --- | --- | --- |
| `make up` fails with "port is already allocated" | Another service owns 4310, 4330, 4342, 4350, 4366 or 4379 | Set `CF_WEB_PORT`, `CF_API_PORT`, `CF_PG_PORT`, `CF_MOCK_LLM_PORT`, `CF_FLOCI_PORT` or `CF_REDIS_PORT` in `deploy/compose/.env`, then `make up` again |
| Compose says "run `make env` first" | `deploy/compose/.env` is missing, or a required secret in it is empty. Running `docker compose` by hand skips `make env` | `make env` (it never overwrites an existing file). To regenerate, delete `deploy/compose/.env` first, then `make down` so the database matches the new demo password |
| `make demo` prints "demo data already present; skipping" | The install was seeded before. The service key is shown only once | Sign in with `CF_DEMO_PASSWORD` from `deploy/compose/.env` and create a key on the API keys page, or `make down && make up && make demo` to start over |
| `make up` is slow the first time | Images build and the Terraform one-shot provisions Floci | Later starts reuse the image cache and the state volume |
| The dashboard dev server shows `Cannot find module './NNN.js'` or a blank page | A stale `apps/web/.next`, for example after a `next build` ran while `next dev` was live | Stop the dev server, `rm -rf apps/web/.next` (or `make clean`), start it again |
| `make test-matrix` says "Floci is not reachable at http://localhost:4366" | The stack is not running, or Floci is on another port | `make up` first. If you changed `CF_FLOCI_PORT`, export it in the shell too: the script reads it from the environment |
| Integration tests refuse to run | The database name lacks `test`, or the host is not local. The suite truncates every table | Point `TEST_DATABASE_URL` at a `*_test` database; `ALLOW_REMOTE_TEST_DB=true` only for a disposable CI host |
| The API refuses to boot: "unsafe production configuration: ..." | `ENVIRONMENT=production` with a development secret, equal secrets, `AUTH_REQUIRED=false`, `COOKIE_SECURE=false` or an endpoint override on `aws` | Fix each item the message lists ([configuration.md](configuration.md#production-boot-guards)) |

## Optimization results

| Symptom | Cause | Fix |
| --- | --- | --- |
| Warning `budget_not_met` and `stats.budget_met: false` | Protected content alone (system and developer messages, the last `preserve_recent_messages`, pinned messages, the latest user turn, their tool call pairs, cited documents) and `must_keep` strings need more than the budget. `details` has `optimized_tokens` and `budget` | Raise `max_input_tokens`, lower `preserve_recent_messages`, unpin messages, or shorten the system prompt. Remember the effective budget is `max_input_tokens - reserve_output_tokens`; through the proxy, a request's `max_tokens` is reserved too |
| 422 `budget_unsatisfiable` | The same situation with `on_budget_failure: "error"` (strict mode) | As above, or use `"warn"` to get the best safe result |
| Warning `required_content_missing` | A `must_keep` string could not be kept within the budget | Raise the budget, or keep fewer required strings |
| Warning `required_content_not_in_input` | A `must_keep` string does not occur in the input at all (check case and whitespace: matching is exact) | Fix the string |
| 422 `unsupported_tokenizer` | The model has no known tokenizer and the request set `allow_estimate: false` | Use a supported model name (OpenAI `gpt-4o`, `gpt-4.1`, `o3` style names are exact), add an alias such as `TOKENIZER_ALIASES=chat-small=gpt-4o-mini`, or allow the estimate |
| `tokenizer.exact: false` and warning `token_estimate` | Expected for models without a known tokenizer (Claude, Gemini, Llama, SmartRouter `auto`). The estimate is `o200k_base` scaled by 1.15, on the safe side | Add a `TOKENIZER_ALIASES` entry if the model really uses an OpenAI encoding |
| Warning `llm_summarizer_failed` | The request asked for `"summarizer": "llm"` and `LLM_SUMMARIZER_URL` is unset, or the call failed or took longer than `LLM_TIMEOUT_S`. `details.reason` says which; the api log has `llm summarizer failed, using extractive` | Set or fix `LLM_SUMMARIZER_URL`, `LLM_SUMMARIZER_API_KEY` and `LLM_SUMMARIZER_MODEL`, or raise `LLM_TIMEOUT_S`. The extractive summary is still a valid result |
| 400 `unknown_profile` | The request's `profile`, or the key's default profile, does not exist (it may have been deleted) | Use a name from `details.profiles`, or edit the key's default profile |
| A document you expected is `dropped` with "no overlap with the query" | With ranking on, documents that share no terms with the query are dropped (not in `conservative`) | Pass `query` explicitly, set `drop_irrelevant_documents: false`, or use `conservative` |
| A repeated request returns instantly with `x-contextforge-cache: HIT` | Expected: identical request, same profiles and settings, within `RESULT_CACHE_TTL_S` | Nothing to fix. Any profile, key or upstream change invalidates it |

## API and proxy

| Symptom | Cause | Fix |
| --- | --- | --- |
| 429 `rate_limited` | The key used up its requests per minute (its own `rpm_limit`, else `DEFAULT_RPM_LIMIT`) | Wait `Retry-After` seconds, or raise the key's limit on the API keys page. Without Redis the limit is per API process |
| 401 `missing_api_key` or `invalid_api_key` | No `Authorization: Bearer cfk_...` header, a key from another product, or the key was created with a different `API_KEY_PEPPER` | Send a ContextForge key; after a pepper change, issue new keys |
| 413 `payload_too_large` | The body exceeds `MAX_BODY_BYTES` | Send it as a background job, split it, or raise the limit |
| 400 `no_upstream` or `unknown_upstream` on `/v1/chat/completions` | No enabled upstream, or the named one does not exist or is disabled | Add or enable one on the Upstreams page, or fix `x-contextforge-upstream` |
| 401, 402 or 429 from the proxy with a body ContextForge did not write | The upstream answered with that status (for example TokenShield's `402 budget_exceeded`); ContextForge passes it through and never retries | Fix it at the upstream: its API key on the Upstreams page, its budget, its limits |
| 502 `upstream_error` or 504 `upstream_timeout` | The upstream is unreachable or slower than `UPSTREAM_TIMEOUT_S` | Check the upstream's base URL (it must end in `/v1`) and health; raise the timeout for slow models |

## Jobs and benchmarks

| Symptom | Cause | Fix |
| --- | --- | --- |
| Jobs stay `queued` | No worker is running | Start `contextforge worker` (Compose: `make logs SERVICE=worker` to see it) |
| A job is `failed` | `error.code` says why: a deterministic refusal such as `unsupported_tokenizer`, or `job_error` after three attempts | Fix the request, or read the worker log for `job failed` with the job id |
| `GET /v1/context/jobs/{id}` returns 404 | The id does not exist, or it was created with a different key | Poll with the key that created it |
| Fetching an old job's result returns 410 `job_result_expired` | The payloads bucket expires objects after 30 days | Collect results soon after jobs finish, or submit the job again |
| New benchmark runs are refused with `benchmark_running` | A run is genuinely in progress (a full run takes seconds), or a worker died mid-run less than 15 minutes ago | Wait: a run still `running` after 15 minutes is marked failed automatically the next time a run is queued |
| The run detail says `content_not_stored` | Runs keep only stats unless `STORE_CONTENT=true` | Turn it on for future runs (content goes to object storage) |
