/**
 * One mapping from engine states to a chip tone, label and explanation, so a status reads
 * the same on the runs list, the drawer, the playground and the overview.
 */

export type Tone = "success" | "savings" | "info" | "primary" | "warning" | "danger" | "neutral";

export interface ChipSpec {
  label: string;
  tone: Tone;
  hint: string;
}

const SOURCE: Record<string, ChipSpec> = {
  api: { label: "API", tone: "primary", hint: "POST /v1/context/optimize from an application." },
  proxy: { label: "Proxy", tone: "info", hint: "An OpenAI-compatible call optimized, then forwarded upstream." },
  job: { label: "Job", tone: "neutral", hint: "A background job for a large input." },
  playground: { label: "Playground", tone: "neutral", hint: "Run from the dashboard playground." },
  benchmark: { label: "Benchmark", tone: "neutral", hint: "Part of a benchmark run." },
};

const STRATEGY: Record<string, ChipSpec> = {
  conservative: {
    label: "Conservative",
    tone: "neutral",
    hint: "Removes only duplicates and tool output bulk. Never drops unique history.",
  },
  balanced: {
    label: "Balanced",
    tone: "primary",
    hint: "The default: dedup, ranking, extractive selection and a structured summary.",
  },
  aggressive: {
    label: "Aggressive",
    tone: "warning",
    hint: "Lower thresholds, and recent tool output may be reduced (errors are always kept).",
  },
};

const JOB: Record<string, ChipSpec> = {
  queued: { label: "Queued", tone: "neutral", hint: "Waiting for a worker." },
  running: { label: "Running", tone: "info", hint: "A worker holds the job's lease." },
  succeeded: { label: "Succeeded", tone: "success", hint: "The result is stored and ready to fetch." },
  failed: { label: "Failed", tone: "danger", hint: "The job stopped; its error says why." },
};

const KIND: Record<string, ChipSpec> = {
  openai: { label: "OpenAI-compatible", tone: "neutral", hint: "OpenAI, Azure OpenAI, vLLM, Ollama, LM Studio, Groq and others." },
  tokenshield: {
    label: "TokenShield",
    tone: "primary",
    hint: "Euron Open TokenShield: budgets enforced before the provider call; its cost header is recorded.",
  },
  smartrouter: {
    label: "SmartRouter",
    tone: "info",
    hint: "Euron Open SmartRouter: model=\"auto\" picks the model; the routed model is recorded.",
  },
};

const WARNING: Record<string, string> = {
  budget_not_met: "Budget not met",
  strategy_escalated: "Escalated to aggressive",
  token_estimate: "Token estimate",
  required_content_missing: "Required content lost",
  required_content_not_in_input: "Required string not in input",
  llm_summarizer_failed: "LLM summarizer fell back",
  input_structure: "Input structure issue",
  structure: "Structure issue",
  citations: "Citation issue",
  summary_in_system_role: "Summary in system role",
};

function fallback(value: string): ChipSpec {
  const label = value ? value.charAt(0).toUpperCase() + value.slice(1).replace(/_/g, " ") : "Unknown";
  return { label, tone: "neutral", hint: "" };
}

export const sourceChip = (v: string | null | undefined): ChipSpec => SOURCE[v ?? ""] ?? fallback(v ?? "");
export const strategyChip = (v: string | null | undefined): ChipSpec => STRATEGY[v ?? ""] ?? fallback(v ?? "");
export const jobChip = (v: string | null | undefined): ChipSpec => JOB[v ?? ""] ?? fallback(v ?? "");
export const kindChip = (v: string | null | undefined): ChipSpec => KIND[v ?? ""] ?? fallback(v ?? "");

export function warningLabel(code: string): string {
  return WARNING[code] ?? code.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** Warnings that mean the result needs a look, as opposed to information. */
export function warningTone(code: string): Tone {
  if (["budget_not_met", "required_content_missing", "structure", "citations"].includes(code)) return "warning";
  if (code === "token_estimate" || code === "strategy_escalated") return "info";
  return "neutral";
}

export const WORKLOADS = ["coding", "agent", "research", "rag", "support", "chat"] as const;
export const SOURCES = ["api", "proxy", "job", "playground"] as const;
export const STRATEGIES = ["conservative", "balanced", "aggressive"] as const;

export function workloadLabel(w: string): string {
  return w === "rag" ? "RAG" : w.charAt(0).toUpperCase() + w.slice(1);
}

/** Fact retention as a tone: anything below 95% deserves attention. */
export function retentionTone(ratio: number): Tone {
  if (ratio >= 0.99) return "savings";
  if (ratio >= 0.95) return "success";
  return "warning";
}
