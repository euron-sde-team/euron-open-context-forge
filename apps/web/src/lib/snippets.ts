/** Copy-paste snippets for the three ways in: library, REST API, OpenAI-compatible proxy. */

export function apiBase(origin: string): string {
  return origin.replace(/\/+$/, "");
}

export function librarySnippet(): string {
  return [
    "from contextforge import OptimizeRequest, optimize",
    "",
    "result = optimize(OptimizeRequest(",
    '    model="gpt-4o",',
    "    messages=history,            # OpenAI chat format",
    "    documents=retrieved_chunks,  # optional: [{id, text, source, metadata}]",
    '    options={"max_input_tokens": 8000, "strategy": "balanced"},',
    "))",
    "print(result.stats.reduction_percent, result.stats.fact_retention)",
    "send_to_model(result.messages)",
  ].join("\n");
}

export function restSnippet(origin: string, key: string): string {
  return [
    `curl ${apiBase(origin)}/v1/context/optimize \\`,
    `  -H "Authorization: Bearer ${key}" \\`,
    '  -H "Content-Type: application/json" \\',
    `  -d '{"model": "gpt-4o", "messages": [...], "options": {"max_input_tokens": 8000}}'`,
  ].join("\n");
}

export function proxySnippet(origin: string, key: string): string {
  return [
    "from openai import OpenAI",
    "",
    "# Point the SDK at ContextForge: every call is optimized, then forwarded upstream.",
    "client = OpenAI(",
    `    base_url="${apiBase(origin)}/v1",`,
    `    api_key="${key}",`,
    '    default_headers={"x-contextforge-max-input-tokens": "8000"},',
    ")",
    "reply = client.chat.completions.create(model=\"gpt-4o\", messages=history)",
  ].join("\n");
}

export function tokenShieldSnippet(origin: string): string {
  return [
    "# Upstream kind: tokenshield",
    "# base_url: https://tokenshield.internal/v1   api_key: tsk_...",
    "#",
    "# app -> ContextForge (fewer tokens) -> TokenShield (budget check) -> provider",
    `client = OpenAI(base_url="${apiBase(origin)}/v1", api_key="cfk_...",`,
    '                default_headers={"x-contextforge-upstream": "tokenshield",',
    '                                 "x-tokenshield-user": "student-42"})',
  ].join("\n");
}

export function smartRouterSnippet(origin: string): string {
  return [
    "# Upstream kind: smartrouter",
    "# base_url: https://smartrouter.internal/v1   api_key: tsr_...",
    "#",
    "# model=\"auto\": the router picks the model after ContextForge shaped the context,",
    "# so counts use a conservative, clearly marked estimate.",
    `client = OpenAI(base_url="${apiBase(origin)}/v1", api_key="cfk_...",`,
    '                default_headers={"x-contextforge-upstream": "smartrouter"})',
    'client.chat.completions.create(model="auto", messages=history)',
  ].join("\n");
}
