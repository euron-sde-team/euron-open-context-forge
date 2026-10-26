# Quickstart (local)

Run the whole system on a laptop with only Docker: Postgres, Redis, the AWS emulator
(provisioned by the same Terraform as production), a deterministic mock LLM, the API, a
worker and the dashboard. No AWS account and no provider keys are needed.

## Prerequisites

- Docker with Compose v2 (Docker Desktop or Docker Engine)
- `make`, `bash`, `openssl`, `curl` (and `jq` for the examples below)
- For running tests outside containers: Python 3.12 with [uv](https://docs.astral.sh/uv/),
  Node 22 and pnpm

## Start

```bash
git clone https://github.com/euron-sde-team/euron-open-context-forge.git
cd euron-open-context-forge
make up      # writes deploy/compose/.env, builds images, applies Terraform on Floci, migrates, starts everything
make demo    # users, keys, upstreams, 60 days of runs, a benchmark run, live traffic through the API
```

`make up` runs `make env` first, which writes `deploy/compose/.env` with random local-only
secrets (it never overwrites an existing file). Then it prints the URLs.

`make demo` runs `contextforge seed-demo` inside the api container. It ends with the
dashboard login and a service key:

```text
  dashboard login   admin@contextforge.local / Forge-...-7
  service key       cfk_..._...  (Coding agent)
```

The password is `CF_DEMO_PASSWORD` from `deploy/compose/.env`. The key belongs to the
"Coding agent" key, whose defaults are the `coding` profile and the `mock-openai` upstream.
Running `make demo` a second time prints `demo data already present; skipping` (the key is
shown only once; `make down` and start again to reset, or create a new key on the API keys
page).

| Service | URL |
| --- | --- |
| Dashboard | http://localhost:4310 |
| Context API | http://localhost:4330/v1/context |
| OpenAI-compatible proxy | http://localhost:4330/v1 |
| API docs (Swagger) | http://localhost:4330/docs |
| Mock LLM (call counts at `/stats`) | http://localhost:4350 |
| Postgres | localhost:4342 |
| Redis | localhost:4379 |
| Floci (AWS emulator) | http://localhost:4366 |

Every port binds to `127.0.0.1` and is overridable in `deploy/compose/.env`:
`CF_WEB_PORT`, `CF_API_PORT`, `CF_MOCK_LLM_PORT`, `CF_PG_PORT`, `CF_REDIS_PORT`,
`CF_FLOCI_PORT`. `CF_LOG_LEVEL` sets the log level, and `CF_REDIS_URL=` (empty) runs the
api and worker without Redis.

The first `make up` takes a few minutes: images build, and the `terraform` one-shot creates
the payloads bucket, the KMS key and the secrets inside Floci before `migrate`, `api` and
`worker` start. Later starts reuse the state volume.

Below, set the key once:

```bash
export CFK=cfk_...    # the key make demo printed
```

## Your first optimization

A conversation with a long, repetitive history and a budget of 300 tokens:

```bash
curl -s http://localhost:4330/v1/context/optimize \
  -H "authorization: Bearer $CFK" \
  -H "content-type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [
      {"role": "system", "content": "You are a release assistant. Answer briefly."},
      {"role": "user", "content": "We ship version 2.4.1 on Friday. The config key is release.channel=stable and the build must pass job ci-7781."},
      {"role": "assistant", "content": "Understood. I will track version 2.4.1, release.channel=stable and job ci-7781."},
      {"role": "user", "content": "The build failed with ImportError: cannot import name Settings from app.config."},
      {"role": "assistant", "content": "That usually means app/config.py was renamed. Check the import in app/main.py."},
      {"role": "user", "content": "The build failed with ImportError: cannot import name Settings from app.config."},
      {"role": "assistant", "content": "Same error again, so the rename is still not fixed in app/main.py."},
      {"role": "user", "content": "Fixed it. What is left before Friday?"}
    ],
    "options": {"max_input_tokens": 300, "preserve_recent_messages": 2}
  }' | jq '{stats, tokenizer, warnings, summary}'
```

What to look at in the response:

- `stats.original_tokens` and `stats.optimized_tokens` are both real counts with the
  model's tokenizer (`tokenizer.id` is `o200k_base`, `tokenizer.exact` is `true`).
- `stats.budget_met` says whether the result fits; `stats.fact_retention` is the share of
  critical facts (versions, keys, ids, error names) that are still present verbatim.
- `optimized_messages` keeps the system message byte for byte and the last two messages
  untouched; the earlier copy of the repeated user turn is gone (the latest occurrence
  wins), and older turns that do not fit the budget are folded into one structured summary
  message (also returned as `summary`).
- `trace` lists every stage (ingest, measure, protect, clean, rank, compress, validate)
  with tokens before and after and the time it took.

The response headers carry `x-contextforge-cache` (`MISS`, then `HIT` when you send the
same body again) and `x-contextforge-run-id`, the run you can open on the dashboard's Runs
page.

Counting tokens alone:

```bash
curl -s http://localhost:4330/v1/context/count-tokens \
  -H "authorization: Bearer $CFK" -H "content-type: application/json" \
  -d '{"model":"gpt-4o","text":"Less context. Fewer tokens. Same intelligence."}'
```

## The playground

Open http://localhost:4310/playground and sign in with the demo login. Pick a sample (or
paste your own messages and documents), set a budget and a strategy, and run it. The page
shows the before and after side by side, the warnings, the per-category allocation and the
stage trace. Playground runs use your dashboard session, not a service key, and are
recorded like any other run.

## The OpenAI-compatible proxy

Point any OpenAI client at `http://localhost:4330/v1` with the `cfk_` key. ContextForge
optimizes the messages, forwards the request to the upstream and returns the upstream's
answer with savings headers.

```bash
curl -si http://localhost:4330/v1/chat/completions \
  -H "authorization: Bearer $CFK" \
  -H "content-type: application/json" \
  -H "x-contextforge-max-input-tokens: 200" \
  -H "x-contextforge-strategy: aggressive" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Summarise our release plan in one line."}]}'
```

Look for `x-contextforge-original-tokens`, `x-contextforge-optimized-tokens`,
`x-contextforge-reduction-percent`, `x-contextforge-budget-met` and
`x-contextforge-run-id`. The demo key forwards to `mock-openai`; send
`x-contextforge-upstream: mock-tokenshield` or `mock-smartrouter` to try the simulated
TokenShield and SmartRouter upstreams. `x-contextforge-optimize: off` forwards the request
untouched.

The same with the OpenAI Python SDK, unmodified:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:4330/v1", api_key="cfk_...")
reply = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Summarise our release plan in one line."}],
    extra_headers={"x-contextforge-max-input-tokens": "4000"},
)
print(reply.choices[0].message.content)
```

## A background job

Large inputs can run in the worker instead of holding a request open. The body is the same
as for `/v1/context/optimize`.

```bash
curl -s http://localhost:4330/v1/context/jobs \
  -H "authorization: Bearer $CFK" -H "content-type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"Plan the 2.4.1 release."}],"options":{"max_input_tokens":2000}}'
# 202 {"id":"6f1c...","status":"queued","poll":"/v1/context/jobs/6f1c..."}

curl -s http://localhost:4330/v1/context/jobs/6f1c... -H "authorization: Bearer $CFK" | jq '.status, .result.stats'
```

Poll until `status` is `succeeded` (the `result` field then holds the full optimize
response) or `failed` (the `error` field says why). The payload and the result live in the
S3 bucket on Floci, not in Postgres. A key can only read its own jobs; any other id
returns 404. The Jobs page on the dashboard lists them all.

## Stop

```bash
make down    # stops containers and deletes their volumes (database, payloads, Floci state)
```

## Next

- [Integrate your application](integrate.md)
- [Configuration reference](configuration.md)
- [Testing](testing.md)
- [Operations](operations.md)
- [Deploy to AWS](deploy-aws.md)
