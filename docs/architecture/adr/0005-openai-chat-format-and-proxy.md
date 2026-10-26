# ADR-0005: The OpenAI chat format is the message contract, and the proxy optimizes then forwards

- **Status:** Accepted
- **Date:** 2026-10-24

## Context

ContextForge has to accept conversations from any application and hand back something that
application can send to its model unchanged. Every major client library, gateway and
self-hosted server (vLLM, Ollama, LM Studio, Azure OpenAI, TokenShield, SmartRouter) speaks
the OpenAI chat completions format, including tool calls and multi-part content. Inventing
an internal message schema would force every caller to convert both ways and would lose
provider-specific fields on the round trip.

Many teams also want the savings without changing code: point the SDK's base URL somewhere
else and be done.

## Decision

**Message contract.** The engine's public types (`engine/types.py`) are the OpenAI chat
format: roles `system`, `developer`, `user`, `assistant`, `tool`; `content` as a string, a
list of parts, or null; `name`; `tool_calls`; `tool_call_id`. Unknown message fields are
allowed and carried through untouched. Non-text content parts (images) are counted but
never rewritten. Messages serialise like the chat API, so an optimized list can be
forwarded as is. The library, `POST /v1/context/optimize` and the proxy share these types.
Structure is validated on the way out: roles stay valid and every tool result still
follows the assistant message that requested it.

**Proxy.** `POST /v1/chat/completions` is an OpenAI-compatible endpoint that:

1. authenticates the `cfk_` service key and resolves the upstream (header
   `x-contextforge-upstream`, then the key's default, then `DEFAULT_UPSTREAM`, then the first
   enabled upstream);
2. optimizes `messages` with the upstream's default budget and strategy, overridable with
   `x-contextforge-max-input-tokens`, `-strategy` and `-profile` headers, keeping room for
   the request's `max_completion_tokens` or `max_tokens`;
3. forwards the body, with only `messages` replaced, to `<base_url>/chat/completions`
   with the upstream's own credential, streaming or not;
4. returns the upstream's status and body unchanged, plus `x-contextforge-*` savings
   headers, and records the run once the upstream has responded.

`x-contextforge-optimize: off` forwards untouched (still authenticated). `GET /v1/models`
relays the upstream's model list. The proxy never retries an upstream call.

## Consequences

**Good**
- Drop-in adoption: an unmodified OpenAI SDK pointed at ContextForge works (acceptance
  criterion 11), and any OpenAI-compatible upstream works behind it.
- Chaining is natural: ContextForge in front of TokenShield in front of a provider, each a
  base URL (see [integrations.md](../integrations.md)).
- Fields ContextForge does not understand survive the round trip.

**Bad / caveats**
- Native Anthropic or Gemini message formats need a client or gateway that speaks the
  OpenAI format first.
- The proxy optimizes only `messages`; tools, response formats and other request fields
  are forwarded as sent and are not counted against the budget.
- Optimization adds the engine's CPU time before the upstream call (milliseconds, see the
  benchmark), and a cache hit only when the identical request was seen within 10 minutes.

## Alternatives considered

- **Own message schema.** Conversion cost for every caller and lossy round trips.
- **SDK middleware only.** One language at a time, and no central history or analytics.
- **Optimize the response or the whole request body.** Out of scope: ContextForge owns the
  input context, not generation parameters.
