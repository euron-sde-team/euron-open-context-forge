# Integrations: TokenShield and SmartRouter

ContextForge is the third layer of the Euron AI efficiency stack:
[TokenShield](https://github.com/euron-sde-team/euron-open-tokenshield) decides whether a
request may spend, SmartRouter decides which model spends it, and ContextForge decides how
little context it needs. Both integrations are **optional adapters**. ContextForge never
depends on either being present: with no TokenShield or SmartRouter upstream configured,
the proxy and every `/v1/context` endpoint work unchanged (`test_adapters_are_optional`).

Integration happens through the OpenAI-compatible proxy
([ADR-0005](adr/0005-openai-chat-format-and-proxy.md)): each upstream has a `kind`, and the
kind selects an adapter.

```
application (OpenAI SDK) --> ContextForge /v1/chat/completions
                                 1. authenticate cfk_ key
                                 2. optimize messages (budget, strategy, profile)
                                 3. forward --> upstream (openai | tokenshield | smartrouter)
                                 4. relay status, body and allowed headers back
                                 5. record the run with the adapter's report
```

## The adapter contract

`apps/api/src/contextforge/integrations/base.py` defines `UpstreamAdapter`:

| Member | Meaning |
| --- | --- |
| `kind` | Upstream kind stored on the `upstreams` row |
| `passthrough_prefixes` | Client request headers forwarded to the upstream, matched by lower-case prefix |
| `expose_prefixes` | Upstream response headers returned to the client, matched by lower-case prefix |
| `report(headers, body)` | Returns `UpstreamReport(model, cost_nusd)`: the model actually used and the cost, if the upstream reports one |

`integrations/registry.py` maps each kind to its adapter; an unknown kind falls back to the
plain OpenAI adapter. Adding an upstream kind means one new file and one registry entry.

Independent of the adapter, the proxy always sends `content-type` and `accept` (and the
client's `x-request-id` when present), sets `Authorization: Bearer <upstream credential>` when the upstream has
one, never forwards the client's `cfk_` key, and drops hop-by-hop response headers
(`content-length`, `transfer-encoding`, `connection`, `content-encoding`, `keep-alive`).
The upstream's `content-type` is always returned.

| Kind | Adapter | Request headers passed through | Response headers returned | Model recorded | Cost recorded |
| --- | --- | --- | --- | --- | --- |
| `openai` | `OpenAIAdapter` (OpenAI, Azure OpenAI, vLLM, Ollama, LM Studio, Groq, ...) | `openai-*`, `idempotency-key` | `openai-*`, `x-ratelimit-*` | `model` in the response body | none |
| `tokenshield` | `TokenShieldAdapter` | `x-tokenshield-*`, `idempotency-key` | `x-tokenshield-*` | `model` in the response body | `x-tokenshield-cost-usd` |
| `smartrouter` | `SmartRouterAdapter` | `x-smartrouter-*`, `idempotency-key` | `x-smartrouter-*` | `x-smartrouter-model`, else `model` in the body | `x-smartrouter-cost-usd` |

## TokenShield

TokenShield enforces budgets before the provider call and reports the cost of every
request. Forwarding through it puts the optimized request under the same budgets, and the
budget sees the smaller, optimized token count.

- **Headers in.** Client `x-tokenshield-*` headers (for example `x-tokenshield-user`,
  `x-tokenshield-task-id`) and `idempotency-key` reach TokenShield untouched, so its
  attribution and replay protection keep working through ContextForge.
- **Headers out.** TokenShield's `x-tokenshield-*` response headers (request id, cache
  status, cost) are returned to the client next to ContextForge's own
  `x-contextforge-*` headers.
- **What is recorded.** `x-tokenshield-cost-usd` is parsed as USD, converted to integer
  nano-dollars (rounded up) and stored as `optimization_runs.upstream_cost_nusd`, shown as
  `upstream_cost_usd`. It sits next to ContextForge's own `cost_avoided_nusd`, which is an
  estimate from a list price table. The two answer different questions: what the call cost,
  and roughly what optimization saved. A header that is missing or does not parse records
  null, never zero.
- **402 pass-through without retry.** When TokenShield refuses a request
  (`402 budget_exceeded`, or any other error status), ContextForge returns the status and
  JSON body to the client unchanged and records the run with `upstream_status = 402`. It
  never retries, and never retries with a smaller context: a budget decision belongs to
  TokenShield, and working around it would defeat the budget. The integration test asserts
  exactly one upstream call.

## SmartRouter

SmartRouter chooses the model after ContextForge has shaped the context, so the target
tokenizer is not known when the budget is applied.

- **`model="auto"` uses an explicit estimate.** `auto` and `auto:<policy>` match no known
  model family, so the tokenizer registry returns its estimate: `o200k_base` counts scaled
  up by 1.15 and rounded up, with id `estimate:o200k_base*1.15` and `exact: false`. The
  overestimate keeps the budget safe whichever model SmartRouter picks. The proxy reports it
  in `x-contextforge-tokenizer` and `x-contextforge-exact: false`, and the run stores
  `exact = false`. No price is known for `auto`, so `cost_avoided_nusd` is null for these
  runs.
- **Headers in.** Client `x-smartrouter-*` headers (policy, task) pass through.
- **Headers out.** SmartRouter's routing headers (`x-smartrouter-model`,
  `x-smartrouter-policy`, ...) are returned to the client.
- **What is recorded.** `x-smartrouter-model` becomes `optimization_runs.upstream_model`
  (falling back to `model` in the response body), and `x-smartrouter-cost-usd`, when
  present, becomes `upstream_cost_nusd`.

## Chaining and the LLM summarizer

- A typical chain is application, ContextForge, TokenShield, provider. Each layer is a base
  URL, so the order is configuration.
- The optional LLM summarizer (`LLM_SUMMARIZER_URL`) is any OpenAI-compatible endpoint.
  Pointing it at TokenShield puts the summarizer's own spend under a budget; pointing it at
  SmartRouter with `LLM_SUMMARIZER_MODEL=auto` lets a cheap model write the summary. It
  calls the endpoint directly, not through an adapter, so its cost is not recorded on the
  run.
- `TOKENIZER_ALIASES` maps alias model names (for example TokenShield model aliases) to an
  encoding or a real model name, so counts stay exact behind an aliasing gateway.

## Proxy headers ContextForge adds

| Header | Meaning |
| --- | --- |
| `x-contextforge-original-tokens` | Tokens before optimization, counted with the target tokenizer |
| `x-contextforge-optimized-tokens` | Tokens after, recounted |
| `x-contextforge-reduction-percent` | Reduction, two decimals |
| `x-contextforge-tokenizer`, `x-contextforge-exact` | Tokenizer id and whether counts are exact |
| `x-contextforge-budget-met` | Whether the optimized context fits the budget |
| `x-contextforge-cache` | `HIT` or `MISS` on the result cache |
| `x-contextforge-run-id` | The recorded run (absent if recording failed) |
| `x-contextforge-warnings` | Comma-separated warning codes, when any |

## The mock LLM is a simulation

`apps/api/src/mockllm/app.py` is a deterministic mock upstream used by the demo, the
integration tests and the benchmark reader. **It is not TokenShield or SmartRouter.** It
simulates the documented header and error contracts of each, and every place that reports
its results labels them as simulated.

| Surface | Simulates | Behaviour |
| --- | --- | --- |
| `/v1/...` | A plain OpenAI-compatible provider | Chat completions (streaming and not) with deterministic answers and approximate usage |
| `/tokenshield/v1/...` | A TokenShield gateway | Adds `x-tokenshield-request-id`, `x-tokenshield-cache: MISS` and `x-tokenshield-cost-usd`; returns `402` with `{"error": {"code": "budget_exceeded", ...}}` for model `over-budget` or header `x-tokenshield-user: over-budget` |
| `/smartrouter/v1/...` | A SmartRouter | Routes `auto` and `auto:<policy>` to `gpt-4o-mini` and adds `x-smartrouter-model`, `-policy`, `-task`, `-request-id` and `-cost-usd` |

Other fixed behaviours: the ContextForge summarizer prompt gets a deliberately incomplete
summary (so the fact guard is exercised), model `reader` answers with the best-matching
sentence from the context (the benchmark's simulated reader), model `fail-500` returns 500,
model `slow` waits 3 s, and `GET /stats` shows call counts and the last request's headers
so tests can assert what was forwarded. In Compose it runs as `mock-llm` on port 4350, and
the demo seed creates three upstreams against it: `mock-openai`, `mock-tokenshield` and
`mock-smartrouter`.

The contract tests are `apps/api/tests/integration/test_integrations.py` (acceptance
criterion 12): TokenShield cost recorded and headers passed through, TokenShield 402 passed
through with one upstream call, SmartRouter `auto` estimated and the routed model recorded,
and every adapter optional.
