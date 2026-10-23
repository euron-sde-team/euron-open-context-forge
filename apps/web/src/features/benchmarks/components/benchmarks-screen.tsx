"use client";

import { GaugeIcon, PlayIcon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { JobChip } from "@/components/status-chip";
import { PageHeader } from "@/components/page-header";
import { Surface, SurfaceHeader } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usePermissions } from "@/features/auth/api";
import { errorMessage } from "@/lib/api/errors";
import type { BenchmarkRunDetail } from "@/lib/api/types";
import { workloadLabel } from "@/lib/chips";
import { cn } from "@/lib/cn";
import { formatDateTime, formatLatency, formatNumber, formatPercent, formatRatio, formatRelative } from "@/lib/format";

import { useBenchmarkRun, useBenchmarkRuns, useDataset, useQueueBenchmark } from "../api";

const METHOD_LABEL: Record<string, string> = {
  "contextforge-balanced": "ContextForge, balanced",
  "contextforge-aggressive": "ContextForge, aggressive",
  "truncate-oldest": "Truncate oldest (baseline)",
  "no-optimization": "No optimization",
};

function Meter({ value, tone }: { value: number; tone: "after" | "saved" | "before" }) {
  return (
    <div className="h-1.5 w-full rounded-full bg-muted" aria-hidden>
      <div
        className={cn("h-full rounded-full", tone === "after" ? "bg-chart-after" : tone === "saved" ? "bg-chart-saved" : "bg-chart-before")}
        style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
      />
    </div>
  );
}

function Summary({ run }: { run: BenchmarkRunDetail }) {
  return (
    <div className="grid gap-3 px-5 pb-5 md:grid-cols-2 xl:grid-cols-4">
      {run.summary.map((s) => {
        const forge = s.method.startsWith("contextforge");
        return (
          <div key={s.method} className={cn("rounded-xl px-4 py-3.5", forge ? "bg-primary-soft/70" : "bg-muted/70")}>
            <div className="text-[13px] font-semibold">{METHOD_LABEL[s.method] ?? s.method}</div>
            <div className="mt-0.5 text-[11.5px] text-muted-foreground">
              {formatNumber(s.tokens_before)} to {formatNumber(s.tokens_after)} tokens, budget met {s.budget_met}/{s.cases}
            </div>
            <dl className="mt-3 space-y-2 text-[12px]">
              {[
                { label: "Reduction", value: s.reduction_percent / 100, text: formatPercent(s.reduction_percent), tone: "after" as const },
                { label: "Fact retention", value: s.fact_retention, text: formatRatio(s.fact_retention), tone: "saved" as const },
                { label: "Citation retention", value: s.citation_retention, text: formatRatio(s.citation_retention), tone: "saved" as const },
                { label: "Reader accuracy (sim.)", value: s.reader_accuracy, text: formatRatio(s.reader_accuracy), tone: "before" as const },
              ].map((m) => (
                <div key={m.label}>
                  <div className="mb-1 flex justify-between">
                    <dt className="text-muted-foreground">{m.label}</dt>
                    <dd className="font-semibold tabular">{m.text}</dd>
                  </div>
                  <Meter value={m.value} tone={m.tone} />
                </div>
              ))}
            </dl>
            {forge && (
              <div className="mt-3 text-[11.5px] text-muted-foreground tabular">
                p50 {formatLatency(s.latency_ms_p50)}, p95 {formatLatency(s.latency_ms_p95)}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Cases({ run }: { run: BenchmarkRunDetail }) {
  const [method, setMethod] = React.useState("contextforge-balanced");
  const rows = run.results.filter((r) => r.method === method);
  return (
    <Surface>
      <SurfaceHeader
        title="Per case"
        description="Every case has a budget well below its original size"
        action={
          <SimpleSelect
            aria-label="Method"
            size="sm"
            className="w-56"
            value={method}
            onValueChange={(v) => setMethod(v || "contextforge-balanced")}
            options={Object.keys(METHOD_LABEL)
              .filter((m) => m !== "no-optimization")
              .map((m) => ({ value: m, label: METHOD_LABEL[m] }))}
          />
        }
      />
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Case</TableHead>
            <TableHead className="text-right">Before</TableHead>
            <TableHead className="text-right">After</TableHead>
            <TableHead className="hidden text-right sm:table-cell">Budget</TableHead>
            <TableHead className="text-right">Facts</TableHead>
            <TableHead className="hidden text-right md:table-cell">Citations</TableHead>
            <TableHead className="hidden lg:table-cell">Missing facts</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.case_id}>
              <TableCell>
                <div className="font-mono text-[12.5px] font-medium">{r.case_id}</div>
                <div className="text-[11.5px] text-muted-foreground">{workloadLabel(r.workload)}</div>
              </TableCell>
              <TableCell className="text-right tabular">{formatNumber(r.tokens_before)}</TableCell>
              <TableCell className="text-right font-medium tabular">{formatNumber(r.tokens_after)}</TableCell>
              <TableCell className="hidden text-right text-muted-foreground tabular sm:table-cell">
                {formatNumber(r.budget)} {r.budget_met ? "" : "(missed)"}
              </TableCell>
              <TableCell className="text-right">
                <Chip tone={r.fact_retention >= 0.999 ? "success" : r.fact_retention >= 0.95 ? "info" : "warning"}>{formatRatio(r.fact_retention, 0)}</Chip>
              </TableCell>
              <TableCell className="hidden text-right tabular md:table-cell">{formatRatio(r.citation_retention, 0)}</TableCell>
              <TableCell className="hidden max-w-72 truncate text-[12px] text-muted-foreground lg:table-cell">
                {r.facts_missing.length ? r.facts_missing.join(", ") : "None"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Surface>
  );
}

function Dataset() {
  const dataset = useDataset();
  return (
    <Surface>
      <SurfaceHeader title="Dataset" description="Synthetic cases generated by a seeded script and committed to the repository" />
      {dataset.isError ? (
        <ErrorState error={dataset.error} compact onRetry={() => void dataset.refetch()} />
      ) : !dataset.data ? (
        <div className="px-5 pb-5">
          <TableSkeleton rows={6} cols={4} />
        </div>
      ) : (
        <ul className="divide-y divide-hairline px-5 pb-3">
          {dataset.data.map((c) => (
            <li key={c.id} className="flex items-start justify-between gap-3 py-2.5">
              <div className="min-w-0">
                <div className="text-[13px] font-medium">{c.title}</div>
                <div className="line-clamp-1 text-[12px] text-muted-foreground">{c.description}</div>
              </div>
              <div className="shrink-0 text-right text-[12px] text-muted-foreground tabular">
                <div className="font-medium text-foreground">{formatNumber(c.tokens)} tokens</div>
                budget {formatNumber(c.max_input_tokens)}, {c.gold_facts} facts
              </div>
            </li>
          ))}
        </ul>
      )}
    </Surface>
  );
}

export function BenchmarksScreen() {
  const { canWrite } = usePermissions();
  const runs = useBenchmarkRuns();
  const queue = useQueueBenchmark();
  const latest = runs.data?.find((r) => r.status === "succeeded");
  const detail = useBenchmarkRun(latest?.id);
  const busy = runs.data?.some((r) => r.status === "queued" || r.status === "running");

  return (
    <>
      <PageHeader
        title="Benchmarks"
        description="Token reduction against fact and citation retention, ContextForge versus truncation at the same budget."
        actions={
          canWrite && (
            <Button
              disabled={busy || queue.isPending}
              onClick={() =>
                queue.mutate(3, {
                  onSuccess: () => toast.success("Benchmark queued. The worker runs it in the background."),
                  onError: (e) => toast.error(errorMessage(e)),
                })
              }
            >
              <PlayIcon />
              {busy ? "Running..." : "Run benchmark"}
            </Button>
          )
        }
      />
      <div className="space-y-4">
        <Surface>
          <SurfaceHeader
            title="Latest results"
            titleExtra={<Hint term="readerAccuracy" />}
            description={
              latest
                ? `Dataset ${latest.dataset_version}, ${latest.cases} cases, ${latest.runs_per_case} timed runs each, finished ${formatRelative(latest.finished_at)}`
                : "Fact retention is strict: a fact counts only when it appears verbatim"
            }
          />
          {runs.isError && !runs.data ? (
            <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />
          ) : !runs.data || (latest && !detail.data) ? (
            <div className="grid gap-3 px-5 pb-5 md:grid-cols-4">
              {Array.from({ length: 4 }, (_, i) => (
                <Skeleton key={i} className="h-56 rounded-xl" />
              ))}
            </div>
          ) : !latest ? (
            <EmptyState
              icon={GaugeIcon}
              title="No benchmark has run yet"
              description="The benchmark optimizes 12 committed cases (coding agents, support threads, RAG, research, agent JSON) at a fixed budget and checks every gold fact and citation survived. It runs in the worker and takes a few seconds."
              action={
                canWrite ? (
                  <Button disabled={busy || queue.isPending} onClick={() => queue.mutate(3)}>
                    <PlayIcon />
                    Run the benchmark
                  </Button>
                ) : undefined
              }
            />
          ) : (
            detail.data && <Summary run={detail.data} />
          )}
        </Surface>
        {detail.data && <Cases run={detail.data} />}
        <div className="grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <Dataset />
          <Surface>
            <SurfaceHeader title="History" description="Every benchmark run" />
            {!runs.data?.length ? (
              <p className="px-5 pb-5 text-[13px] text-muted-foreground">Runs appear here after the first benchmark.</p>
            ) : (
              <ul className="divide-y divide-hairline px-5 pb-3">
                {runs.data.map((r) => {
                  const forge = r.summary.find((s) => s.method === "contextforge-balanced");
                  return (
                    <li key={r.id} className="flex items-center justify-between gap-3 py-2.5">
                      <div>
                        <div className="text-[13px] font-medium">{formatDateTime(r.created_at)}</div>
                        <div className="text-[12px] text-muted-foreground">
                          {forge
                            ? `${formatPercent(forge.reduction_percent)} fewer tokens, ${formatRatio(forge.fact_retention)} facts kept`
                            : r.error ?? "In progress"}
                        </div>
                      </div>
                      <JobChip value={r.status} />
                    </li>
                  );
                })}
              </ul>
            )}
          </Surface>
        </div>
      </div>
    </>
  );
}
