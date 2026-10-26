"use client";

import { ArrowRightIcon, FileTextIcon, PlayIcon, SparklesIcon, WandSparklesIcon } from "lucide-react";
import * as React from "react";

import { AllocationView, TraceView, WarningsView } from "@/components/engine-views";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { PageHeader } from "@/components/page-header";
import { Segmented } from "@/components/segmented";
import { StrategyChip } from "@/components/status-chip";
import { Surface, SurfaceHeader } from "@/components/surface";
import { TokenBar } from "@/components/token-bar";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Input, Textarea } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { errorMessage } from "@/lib/api/errors";
import type {
  ChatMessage,
  ContextDocument,
  OptimizeRequest,
  OptimizeResponse,
  Strategy,
  Workload,
} from "@/lib/api/types";
import { retentionTone, STRATEGIES, WORKLOADS, workloadLabel } from "@/lib/chips";
import { cn } from "@/lib/cn";
import { formatLatency, formatNumber, formatPercent, formatUsd } from "@/lib/format";

import { useOptimize, useSample, useSamples } from "../api";
import { messageStatuses, type MessageStatus } from "../diff";

const STARTER: { messages: ChatMessage[]; documents: ContextDocument[] } = {
  messages: [
    { role: "system", content: "You are a helpful support assistant." },
    { role: "user", content: "My account is ACC-77120. I need to upgrade 42 seats before 2026-11-01." },
    { role: "assistant", content: "Business costs $49 per seat. We must not change the billing contact without verification." },
    { role: "user", content: "Great. What happens to our API keys during the upgrade?" },
  ],
  documents: [],
};

const STATUS_TONE: Record<MessageStatus, "success" | "warning" | "danger" | "primary" | "neutral"> = {
  kept: "neutral",
  shortened: "warning",
  removed: "danger",
  summary: "primary",
  added: "primary",
};

function text(m: ChatMessage): string {
  if (typeof m.content === "string") return m.content;
  if (Array.isArray(m.content)) return m.content.map((p) => p.text ?? `[${p.type}]`).join("\n");
  if (m.tool_calls?.length) return m.tool_calls.map((c) => `${c.function.name}(${c.function.arguments})`).join("\n");
  return "";
}

function MessageCard({ m, status }: { m: ChatMessage; status: MessageStatus }) {
  const [open, setOpen] = React.useState(false);
  const body = text(m);
  const long = body.length > 420;
  return (
    <li className={cn("rounded-lg bg-muted/60 px-3 py-2.5", status === "removed" && "opacity-60", status === "summary" && "bg-primary-soft/60")}>
      <div className="mb-1 flex items-center gap-1.5">
        <span className="font-mono text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{m.role}</span>
        {m.tool_calls?.length ? <Chip tone="neutral">tool call</Chip> : null}
        <Chip tone={STATUS_TONE[status]} className="ml-auto">
          {status}
        </Chip>
      </div>
      <pre className={cn("font-mono text-[12px] leading-relaxed break-words whitespace-pre-wrap text-foreground/90", status === "removed" && "line-through decoration-faint")}>
        {long && !open ? `${body.slice(0, 420)}...` : body || <span className="text-faint">(no text)</span>}
      </pre>
      {long && (
        <button type="button" onClick={() => setOpen((o) => !o)} className="mt-1 text-[12px] font-medium text-primary hover:underline">
          {open ? "Show less" : `Show all ${formatNumber(body.length)} characters`}
        </button>
      )}
    </li>
  );
}

function Headline({ r }: { r: OptimizeResponse }) {
  const s = r.stats;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
        <div>
          <div className="text-[12px] text-muted-foreground">Tokens</div>
          <div className="flex items-center gap-2 text-[26px] leading-none font-semibold tracking-[-0.02em] tabular">
            <span className="text-muted-foreground">{formatNumber(s.original_tokens)}</span>
            <ArrowRightIcon className="size-5 text-faint" />
            <span>{formatNumber(s.optimized_tokens)}</span>
          </div>
        </div>
        <div>
          <div className="text-[12px] text-muted-foreground">Reduction</div>
          <div className="text-[26px] leading-none font-semibold text-savings tabular">{formatPercent(s.reduction_percent)}</div>
        </div>
        <div className="flex flex-wrap gap-1.5 pb-0.5">
          <Chip tone={s.budget_met ? "success" : "warning"} dot>
            {s.budget == null ? "No budget" : s.budget_met ? `Fits ${formatNumber(s.budget)}` : `Over ${formatNumber(s.budget)}`}
          </Chip>
          <Chip tone={retentionTone(s.fact_retention)} dot>
            {s.facts_total ? `${s.facts_retained}/${s.facts_total} facts kept` : "No critical facts"}
          </Chip>
          <Chip tone={r.tokenizer.exact ? "success" : "info"}>{r.tokenizer.exact ? `Exact: ${r.tokenizer.id}` : r.tokenizer.id}</Chip>
          <StrategyChip value={r.strategy} />
          <Chip tone="neutral">
            {workloadLabel(r.workload)}
            {r.profile !== r.workload ? ` / ${r.profile}` : ""}
          </Chip>
        </div>
      </div>
      <TokenBar before={s.original_tokens} after={s.optimized_tokens} budget={s.budget} />
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-[12.5px] text-muted-foreground">
        <span>
          Messages {s.messages_in} to {s.messages_out}
        </span>
        {s.documents_in > 0 && (
          <span>
            Documents {s.documents_in} to {s.documents_out}
          </span>
        )}
        <span>Engine {formatLatency(s.latency_ms)}</span>
        {r.cost_avoided_usd != null && (
          <span className="flex items-center gap-1">
            {formatUsd(r.cost_avoided_usd)} avoided per call (est.) <Hint term="costAvoided" />
          </span>
        )}
        {r.cached && <span className="font-medium text-savings">Result cache hit</span>}
      </div>
    </div>
  );
}

function Documents({ input, r }: { input: ContextDocument[]; r: OptimizeResponse }) {
  if (!input.length) {
    return <p className="text-[13px] text-muted-foreground">This input has no retrieved documents. Load a RAG or research sample to see citation mapping.</p>;
  }
  const kept = new Map(r.optimized_documents.map((d, i) => [d.id, i + 1]));
  const order: Record<string, number> = { kept: 0, compressed: 1, merged: 2, dropped: 3 };
  // Kept passages first in their rank order, then merged duplicates, then dropped noise.
  const sorted = [...input].sort((a, b) => {
    const sa = order[r.citation_map[a.id]?.status ?? "dropped"] ?? 4;
    const sb = order[r.citation_map[b.id]?.status ?? "dropped"] ?? 4;
    return sa - sb || (kept.get(a.id) ?? 0) - (kept.get(b.id) ?? 0);
  });
  return (
    <ul className="space-y-1.5">
      {sorted.map((d) => {
        const entry = r.citation_map[d.id];
        const tone = entry?.status === "kept" ? "success" : entry?.status === "compressed" ? "warning" : entry?.status === "merged" ? "info" : "danger";
        return (
          <li key={d.id} className="flex items-start gap-3 rounded-lg bg-muted/60 px-3 py-2">
            <span className="w-8 shrink-0 pt-0.5 text-right font-mono text-[11.5px] text-faint tabular">{kept.get(d.id) ? `#${kept.get(d.id)}` : ""}</span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="font-mono text-[12px] font-semibold">[{d.id}]</span>
                <Chip tone={tone}>{entry?.status ?? "unknown"}</Chip>
                {entry?.into && <span className="text-[12px] text-muted-foreground">into [{entry.into}]</span>}
                {entry?.reason && <span className="text-[12px] text-muted-foreground">{entry.reason}</span>}
              </div>
              <p className="mt-0.5 line-clamp-2 text-[12.5px] text-muted-foreground">{d.title ? `${d.title}: ` : ""}{d.text}</p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function PlaygroundScreen() {
  const samples = useSamples();
  const [sampleId, setSampleId] = React.useState<string | null>(null);
  const sample = useSample(sampleId);
  const optimize = useOptimize();
  const [model, setModel] = React.useState("gpt-4o");
  const [budget, setBudget] = React.useState("400");
  const [strategy, setStrategy] = React.useState<Strategy>("balanced");
  const [workload, setWorkload] = React.useState<Workload>("auto");
  const [summarize, setSummarize] = React.useState(true);
  const [raw, setRaw] = React.useState(() => JSON.stringify(STARTER, null, 2));
  const [parseError, setParseError] = React.useState<string | null>(null);
  const [lastInput, setLastInput] = React.useState<{ messages: ChatMessage[]; documents: ContextDocument[] } | null>(null);

  React.useEffect(() => {
    if (!sample.data) return;
    const body = sample.data as unknown as OptimizeRequest;
    setRaw(JSON.stringify({ messages: body.messages ?? [], documents: body.documents ?? [] }, null, 2));
    setModel(body.model);
    setBudget(String(body.options?.max_input_tokens ?? ""));
    setParseError(null);
  }, [sample.data]);

  function run() {
    let parsed: { messages?: ChatMessage[]; documents?: ContextDocument[] };
    try {
      parsed = JSON.parse(raw) as typeof parsed;
    } catch (e) {
      setParseError(`The input is not valid JSON: ${(e as Error).message}`);
      return;
    }
    if (!Array.isArray(parsed.messages) && !Array.isArray(parsed.documents)) {
      setParseError('Provide {"messages": [...], "documents": [...]} in the OpenAI chat format.');
      return;
    }
    const n = budget.trim() ? Number(budget) : null;
    if (n != null && (!Number.isInteger(n) || n < 1)) {
      setParseError("The budget must be a whole number of tokens, or empty to only clean.");
      return;
    }
    setParseError(null);
    const input = { messages: parsed.messages ?? [], documents: parsed.documents ?? [] };
    setLastInput(input);
    optimize.mutate({
      model: model.trim() || "gpt-4o",
      ...input,
      options: { max_input_tokens: n, strategy, workload, summarize_history: summarize },
    });
  }

  const r = optimize.data;
  const statuses = r && lastInput ? messageStatuses(lastInput.messages, r.optimized_messages) : null;

  return (
    <>
      <PageHeader
        title="Playground"
        description="Paste a conversation and retrieved documents, or load a benchmark sample, and see exactly what ContextForge keeps."
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <Surface className="flex flex-col">
          <SurfaceHeader title="Input" description="OpenAI chat messages plus optional documents" />
          <div className="space-y-4 px-5 pb-5">
            <Field
              label="Start from a sample"
              htmlFor="sample"
              error={
                samples.isError
                  ? `Could not load the samples: ${errorMessage(samples.error)}`
                  : sample.isError
                    ? `Could not load that sample: ${errorMessage(sample.error)}`
                    : undefined
              }
            >
              <SimpleSelect
                id="sample"
                value={sampleId ?? ""}
                onValueChange={(v) => setSampleId(v || null)}
                placeholder={samples.isLoading ? "Loading samples..." : "Choose a benchmark sample"}
                options={(samples.data ?? []).map((s) => ({
                  value: s.id,
                  label: `${s.title} (${formatNumber(s.tokens)} tokens)`,
                }))}
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Model" htmlFor="model" hint="Picks the tokenizer">
                <Input id="model" value={model} onChange={(e) => setModel(e.target.value)} className="font-mono" />
              </Field>
              <Field label="Budget (tokens)" htmlFor="budget" hint="Empty: clean only">
                <Input id="budget" inputMode="numeric" value={budget} onChange={(e) => setBudget(e.target.value.replace(/[^\d]/g, ""))} className="tabular" />
              </Field>
            </div>
            <Field label="Strategy" labelExtra={<Hint term="strategy" />}>
              <Segmented<Strategy>
                ariaLabel="Strategy"
                value={strategy}
                onChange={setStrategy}
                options={STRATEGIES.map((s) => ({ value: s, label: s.charAt(0).toUpperCase() + s.slice(1) }))}
              />
            </Field>
            <div className="grid grid-cols-2 items-end gap-3">
              <Field label="Workload" htmlFor="workload" labelExtra={<Hint term="workload" />}>
                <SimpleSelect
                  id="workload"
                  value={workload}
                  onValueChange={(v) => setWorkload((v || "auto") as Workload)}
                  options={[{ value: "auto", label: "Detect automatically" }, ...WORKLOADS.map((w) => ({ value: w, label: workloadLabel(w) }))]}
                />
              </Field>
              <label className="flex h-9 items-center gap-2 text-[13px]">
                <Switch checked={summarize} onCheckedChange={setSummarize} aria-label="Summarise dropped history" />
                Summarise dropped history
              </label>
            </div>
            <Field label="Messages and documents (JSON)" htmlFor="raw" error={parseError}>
              <Textarea
                id="raw"
                value={raw}
                onChange={(e) => setRaw(e.target.value)}
                spellCheck={false}
                className="h-80 resize-y font-mono text-[12px] leading-relaxed"
              />
            </Field>
            <Button className="w-full" size="lg" onClick={run} disabled={optimize.isPending || sample.isFetching}>
              {optimize.isPending ? <SparklesIcon className="animate-pulse" /> : <PlayIcon />}
              {optimize.isPending ? "Optimizing..." : "Optimize"}
            </Button>
          </div>
        </Surface>

        <div className="min-w-0 space-y-4">
          {optimize.isError ? (
            <Surface>
              <ErrorState title="The optimization was refused" error={optimize.error} onRetry={run} />
              <FieldError className="sr-only">{errorMessage(optimize.error)}</FieldError>
            </Surface>
          ) : optimize.isPending && !r ? (
            <Surface className="p-5">
              <Skeleton className="h-28 w-full" />
            </Surface>
          ) : !r ? (
            <Surface>
              <EmptyState
                icon={WandSparklesIcon}
                title="Run an optimization"
                description="Choose a sample (a coding agent stuck on a test, a long support thread, a noisy retrieval) or paste your own messages, set a budget, and press Optimize. Nothing is sent to a model: the engine is deterministic and runs locally."
                action={
                  <Button onClick={run}>
                    <PlayIcon />
                    Optimize the starter conversation
                  </Button>
                }
              />
            </Surface>
          ) : (
            <>
              <Surface className="p-5" aria-live="polite">
                <Headline r={r} />
              </Surface>
              <Surface>
                <Tabs defaultValue="messages" className="gap-4 px-5 py-4">
                  <TabsList>
                    <TabsTrigger value="messages">Messages</TabsTrigger>
                    <TabsTrigger value="documents">Documents</TabsTrigger>
                    <TabsTrigger value="trace">Trace</TabsTrigger>
                    <TabsTrigger value="budget">Budget</TabsTrigger>
                    <TabsTrigger value="warnings">
                      Warnings
                      {r.warnings.length > 0 && <Chip tone="warning">{r.warnings.length}</Chip>}
                    </TabsTrigger>
                  </TabsList>
                  <TabsContent value="messages">
                    <div className="grid gap-4 lg:grid-cols-2">
                      <div className="min-w-0">
                        <h3 className="mb-2 text-[12.5px] font-semibold text-muted-foreground">Before</h3>
                        <ul className="space-y-2">
                          {(lastInput?.messages ?? []).map((m, i) => (
                            <MessageCard key={i} m={m} status={statuses?.before[i] ?? "kept"} />
                          ))}
                        </ul>
                      </div>
                      <div className="min-w-0">
                        <h3 className="mb-2 text-[12.5px] font-semibold text-muted-foreground">After</h3>
                        <ul className="space-y-2">
                          {r.optimized_messages.map((m, i) => (
                            <MessageCard key={i} m={m} status={statuses?.after[i] ?? "kept"} />
                          ))}
                        </ul>
                      </div>
                    </div>
                  </TabsContent>
                  <TabsContent value="documents">
                    <Documents input={lastInput?.documents ?? []} r={r} />
                  </TabsContent>
                  <TabsContent value="trace">
                    <TraceView trace={r.trace} />
                  </TabsContent>
                  <TabsContent value="budget">
                    <AllocationView allocation={r.allocation} />
                    {r.summary && (
                      <div className="mt-5">
                        <h3 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold">
                          <FileTextIcon className="size-4 text-primary" />
                          Summary of dropped history
                        </h3>
                        <pre className="rounded-lg bg-muted/70 px-3 py-2.5 font-mono text-[12px] leading-relaxed whitespace-pre-wrap">{r.summary}</pre>
                      </div>
                    )}
                  </TabsContent>
                  <TabsContent value="warnings">
                    <WarningsView warnings={r.warnings} />
                  </TabsContent>
                </Tabs>
              </Surface>
            </>
          )}
        </div>
      </div>
    </>
  );
}
