# Integrate your application

Runnable examples for each way in are in [examples/](../../examples/).

There are three ways in. All three run the same engine and accept the same request shape
(`model`, `messages`, `documents`, `options`), so a request that works in-process works
over the wire unchanged.

| Way in | Use it when | Recorded on the dashboard |
| --- | --- | --- |
| Python library | Your app is Python and you want no extra hop | No |
| REST API (`/v1/context/*`) | Any language; you call the model yourself | Yes |
| OpenAI-compatible proxy (`/v1/chat/completions`) | You want a drop-in: change the base URL and key | Yes, with the upstream's model, status and cost |

## 1. Python library

The engine is pure Python with no I/O: no network, no database, no LLM. Install the
package from the repository (`pip install ./apps/api`, or `uv pip install ./apps/api`) and
import it:

```python
from contextforge import optimize, OptimizeRequest

result = optimize(
    OptimizeRequest(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a support agent for Acme Cloud."},
            {"role": "user", "content": "My invoice INV-20931 shows two charges for March."},
            # ... the rest of the conversation
        ],
        options={"max_input_tokens": 4000, "workload": "support"},
    )
)

print(result.stats.original_tokens, "->", result.stats.optimized_tokens)
print(result.stats.budget_met, result.stats.fact_retention, [w.code for w in result.warnings])
messages_to_send = [m.model_dump() for m in result.messages]
```

The library returns `OptimizeResult`: the same fields as the REST response below, except
that the lists are named `messages` and `documents`, and there is no `profile`, `run_id`,
`cached` or `cost_avoided_usd` (those come from the service).

`optimize()` takes three optional keyword arguments:

- `registry`: a `TokenizerRegistry`, for aliases (`TokenizerRegistry({"chat-small":
  "gpt-4o-mini"})`) or custom tokenizer adapters (see [walkthrough.md](walkthrough.md)).
- `profiles`: a `dict[str, Profile]` replacing the built-in workload profiles
  (`contextforge.engine.BUILTIN_PROFILES`).
- `summarizer`: any object with `summarize(SummaryInput) -> SummaryOutput`. The default is
  the deterministic `ExtractiveSummarizer`. In the library, `options.summarizer` does not
  pick one; pass `summarizer=LLMSummarizer(base_url, model, api_key)` from
  `contextforge.llm.summarizer` to use an LLM.

It raises `UnsupportedTokenizerError` when the model's tokenizer is unknown and
`allow_estimate` is false, and `BudgetUnsatisfiableError` (with the best result on
`.result`) when `on_budget_failure="error"` and the budget cannot be met safely.

tiktoken downloads its two encodings once, on first use, and caches them. For a machine
with no network, warm the cache at build time and set `TIKTOKEN_CACHE_DIR`, as the API
image does.

## 2. REST API

Authenticate every `/v1` call with a service key from the dashboard (API keys page):
`Authorization: Bearer cfk_<prefix>_<secret>`. `x-api-key: cfk_...` is accepted too.

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/context/optimize` | Optimize messages and documents to fit a budget |
| `POST /v1/context/count-tokens` | Count tokens with the model's tokenizer (or a marked estimate) |
| `POST /v1/context/summarize` | Structured summary of a conversation |
| `POST /v1/context/rank` | Rank passages by relevance, dropping duplicates and irrelevant ones |
| `POST /v1/context/jobs` | Optimize in the background (202 with a poll path) |
| `GET /v1/context/jobs/{id}` | Job status, and the full result once it succeeded |

The full schema is in [docs/api/openapi.yaml](../api/openapi.yaml) and live at
`/docs` on a running API.

### Optimize

```bash
curl -s http://localhost:4330/v1/context/optimize \
  -H "authorization: Bearer $CFK" -H "content-type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "How do I rotate the signing key?"}],
    "documents": [
      {"id": "kb-12", "source": "kb/keys.md", "text": "Rotate the signing key with keyctl rotate --id signing."},
      {"id": "kb-13", "source": "kb/keys.md", "text": "Rotate the signing key with keyctl rotate --id signing."},
      {"id": "kb-40", "source": "kb/billing.md", "text": "Invoices are issued on the first business day."}
    ],
    "options": {"max_input_tokens": 2000, "workload": "rag"}
  }' | jq '.citation_map, .stats.documents_out'
```

Every input document id appears in `citation_map` with a status: `kept`, `compressed`
(shortened to its best sentences), `merged` (a duplicate, with `into` naming the kept id)
or `dropped` (with a `reason`). Documents are never renamed, so citations in the answer
still resolve.

Response fields (`OptimizeResponse` in `apps/api/src/contextforge/context/schemas.py`):

| Field | Meaning |
| --- | --- |
| `optimized_messages` | The message list to send, in chat format. Unknown message fields are carried through untouched |
| `optimized_documents` | The documents to send, with ids, sources and metadata intact |
| `citation_map` | Input document id to `{status, into, reason}` |
| `citations_preserved` | False when a citation could not be preserved (warning `citations`) |
| `stats` | `original_tokens`, `optimized_tokens`, `tokens_removed`, `reduction_percent`, `budget`, `budget_met`, `messages_in`, `messages_out`, `documents_in`, `documents_out`, `facts_total`, `facts_retained`, `fact_retention`, `latency_ms`. Counts are recounted on the output, never estimated from ratios |
| `tokenizer` | `{id, exact, model}`. `exact: false` and an id like `estimate:o200k_base*1.15` mean a deliberate overestimate |
| `strategy` | The strategy that produced the result (`aggressive` after an escalation) |
| `workload` | The workload used (detected when `auto`) |
| `profile` | The profile name used (the workload name when none was given) |
| `allocation` | Per category (`history`, `tool`, `documents`, `summary`): weight, budget and tokens used |
| `summary` | The summary text, or null |
| `warnings` | `{code, message, details}` entries, see below |
| `trace` | One step per stage: `stage`, `tokens_before`, `tokens_after`, `items_removed`, `ms`, `notes` |
| `run_id` | The recorded run (also in the `x-contextforge-run-id` header) |
| `cached` | Served from the result cache (also `x-contextforge-cache: HIT`) |
| `cost_avoided_usd` | Estimate: tokens removed times the model's list input price (`MODEL_PRICES`); null for unknown models |

Warning codes (the request still succeeds):

| Code | Meaning |
| --- | --- |
| `budget_not_met` | Protected and required content alone needs more than the budget. `details` has `optimized_tokens`, `budget`, `protected_messages` |
| `strategy_escalated` | `balanced` missed the budget, so `aggressive` was applied |
| `token_estimate` | No tokenizer is known for the model; counts are a conservative estimate |
| `required_content_missing` | Some `must_keep` strings could not be kept |
| `required_content_not_in_input` | Some `must_keep` strings do not occur in the input at all |
| `llm_summarizer_failed` | The LLM summarizer failed or is not configured; the extractive one was used |
| `input_structure` | The input has tool call problems; they are passed through unchanged |
| `structure` | The output has structural problems (should not happen; report it) |
| `citations` | Some citations could not be preserved |
| `summary_in_system_role` | `summary_role: "system"` placed quoted text in the system role, as requested |

### Count, summarize, rank

```bash
# Per-message and per-document counts
curl -s http://localhost:4330/v1/context/count-tokens -H "authorization: Bearer $CFK" \
  -H "content-type: application/json" \
  -d '{"model":"claude-sonnet-4-5","text":"hello world","allow_estimate":true}'

# A structured summary (goals, requirements, decisions, facts, errors, open questions)
curl -s http://localhost:4330/v1/context/summarize -H "authorization: Bearer $CFK" \
  -H "content-type: application/json" \
  -d '{"model":"gpt-4o","max_summary_tokens":300,"messages":[{"role":"user","content":"Deploy service billing-api to eu-west-1 by Friday."}]}'

# Rank passages: ranked, dropped (with duplicate_of) and tokens_selected
curl -s http://localhost:4330/v1/context/rank -H "authorization: Bearer $CFK" \
  -H "content-type: application/json" \
  -d '{"query":"rotate the signing key","top_k":5,"passages":[{"id":"a","text":"Rotate the signing key with keyctl."},{"id":"b","text":"Invoices are monthly."}]}'
```

`summarize` excludes system and developer messages unless `include_system` is true, and
reports `facts_total` and `facts_covered`. `rank` blends BM25 relevance with a
retriever `score` when passages carry one, and drops exact and near duplicates,
zero-relevance passages, and anything beyond `top_k` or `max_tokens`.

### Background jobs

`POST /v1/context/jobs` takes an optimize body and answers 202 with
`{"id", "status": "queued", "poll": "/v1/context/jobs/<id>"}`. `GET` the poll path until
`status` is `succeeded` (with `result`, a full optimize response, and `run_id`) or
`failed` (with `error`). The payload and result are stored in object storage; only their
keys are in Postgres. A key sees only its own jobs.

## 3. OpenAI-compatible proxy

Point an unmodified OpenAI SDK at ContextForge. Every chat completion is optimized first,
then forwarded, streaming or not, to an upstream you configured on the Upstreams page.

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:4330/v1", api_key="cfk_...")
stream = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=history,
    stream=True,
    extra_headers={
        "x-contextforge-max-input-tokens": "8000",
        "x-contextforge-profile": "coding",
    },
)
```

The upstream is chosen by `x-contextforge-upstream`, then the key's default upstream,
then `DEFAULT_UPSTREAM`, then the first enabled upstream. The budget and strategy default
to the upstream's settings. `GET /v1/models` lists the chosen upstream's models. The full
header list is in [configuration.md](configuration.md#proxy-request-headers).

Upstream errors are returned to the client with their own status and body; ContextForge
does not retry them.

### Upstream kinds

An upstream has a name, a base URL (OpenAI-compatible, ending in `/v1`), an optional API
key (sealed with KMS or the local master key before it is stored), a default budget, a
default strategy and a kind. The kind decides which headers pass through and how the run
is recorded (`apps/api/src/contextforge/integrations/`).

| Kind | Passes through to the upstream | Returns to the client | Recorded on the run |
| --- | --- | --- | --- |
| `openai` | `openai-*`, `idempotency-key` | `openai-*`, `x-ratelimit-*` | Model from the response body |
| `tokenshield` | `x-tokenshield-*`, `idempotency-key` | `x-tokenshield-*` | Model from the body; cost from `x-tokenshield-cost-usd` |
| `smartrouter` | `x-smartrouter-*`, `idempotency-key` | `x-smartrouter-*` | Model from `x-smartrouter-model` (else the body); cost from `x-smartrouter-cost-usd` |

A client's `x-request-id` is always forwarded, and the upstream's `content-type` is always returned.

**TokenShield** ([euron-open-tokenshield](https://github.com/euron-sde-team/euron-open-tokenshield))
enforces budgets before the provider call. Forwarding through it puts the optimized
request under the same budgets. Its `402 budget_exceeded` (or any other TokenShield error)
reaches your client unchanged: ContextForge never retries around a budget decision. Set
`TOKENIZER_ALIASES` for TokenShield model aliases (for example `chat-small=gpt-4o-mini`) so
counts stay exact.

**SmartRouter** picks the model after ContextForge has shaped the context, so the target
tokenizer is unknown in advance. `model="auto"` (or `auto:<policy>`) matches no known
tokenizer, so ContextForge budgets with the explicit estimate (`exact: false`), which
overestimates on purpose so the budget holds whichever model is chosen.

The integration tests for both kinds run against simulated upstreams (the mock LLM's
`/tokenshield/v1` and `/smartrouter/v1` surfaces) that follow the documented header and
error contracts.

## Error codes

Errors share one envelope, compatible with OpenAI SDK error parsing:

```json
{"error": {"code": "unsupported_tokenizer", "type": "invalid_request_error",
           "message": "No tokenizer is configured for 'acme-7b' and estimates were refused. ...",
           "details": {"model": "acme-7b"}}}
```

Context API and proxy:

| HTTP | Code | When |
| --- | --- | --- |
| 400 | `unknown_profile` | `options.profile` (or the key's default profile) does not exist. `details.profiles` lists valid names |
| 400 | `invalid_json`, `invalid_request` | The proxy body is not JSON, lacks `model` or `messages`, or the messages are not chat format |
| 400 | `invalid_header` | An `x-contextforge-*` header has an invalid value |
| 400 | `no_upstream` | No upstream is configured |
| 400 | `unknown_upstream` | The named upstream does not exist or is disabled |
| 401 | `missing_api_key`, `invalid_api_key`, `revoked_api_key`, `expired_api_key` | Service key problems |
| 404 | `not_found` | The job does not exist or belongs to another key |
| 413 | `payload_too_large` | The body is larger than `MAX_BODY_BYTES` |
| 422 | `validation_error` | The body does not match the schema. `details.errors` lists each field |
| 422 | `unsupported_tokenizer` | Unknown tokenizer and `allow_estimate: false` |
| 422 | `budget_unsatisfiable` | `on_budget_failure: "error"` and the budget cannot be met without losing protected or required content. `details` has `optimized_tokens`, `budget`, `warnings` |
| 429 | `rate_limited` | The key's requests per minute were used up. `Retry-After` and `details.retry_after_s` say when to retry |
| 502 | `upstream_error` | The upstream is unreachable |
| 504 | `upstream_timeout` | The upstream did not answer within `UPSTREAM_TIMEOUT_S` |
| 500 | `internal_error` | A bug; the log line with the same `x-request-id` has the stack trace |

A failed job stores its error in the same shape: the code above for a deterministic
refusal, or `job_error` after three failed attempts.

Dashboard API (`/api/v1/*`): 401 `not_signed_in`, `session_expired`,
`invalid_credentials`, `account_locked`, `account_disabled`; 403 `csrf_required`,
`insufficient_role`; 400 `weak_password`; 409 `email_taken`, `last_owner`,
`upstream_exists`, `profile_exists`, `benchmark_running`; 404 `content_not_stored`.

Jobs: 410 `job_result_expired` when a finished job's result has expired from storage.
