"use client";

import { CheckCircle2Icon, TriangleAlertIcon } from "lucide-react";

import { Hint } from "@/components/hint";
import { WarningChip } from "@/components/status-chip";
import type { Allocation, OptimizeWarning, TraceStep } from "@/lib/api/types";
import { warningTone } from "@/lib/chips";
import { cn } from "@/lib/cn";
import { formatNumber, formatTokens } from "@/lib/format";

const STAGE_LABEL: Record<string, string> = {
  ingest: "Ingest",
  measure: "Measure",
  protect: "Protect",
  clean: "Clean",
  rank: "Rank",
  compress: "Compress",
  validate: "Validate",
};

const STAGE_HINT: Record<string, string> = {
  ingest: "Validate the input, detect the workload and pick the profile.",
  measure: "Count every message and document with the target tokenizer.",
  protect: "Mark what is never rewritten: system, recent turns, pins, cited documents.",
  clean: "Drop empty and duplicate content, collapse repeated tool runs, reduce tool output bulk.",
  rank: "Score what is left by relevance, recency and importance.",
  compress: "Fit the budget per category, extract sentences, summarise what was dropped.",
  validate: "Recount, check the budget, structure, citations and fact retention.",
};

/** The eight-stage pipeline as a vertical timeline: tokens in, tokens out, what happened. */
export function TraceView({ trace }: { trace: TraceStep[] }) {
  if (!trace.length) return <p className="text-[13px] text-muted-foreground">This run was recorded without a trace.</p>;
  return (
    <ol className="relative space-y-3 pl-6">
      <span aria-hidden className="absolute top-1.5 bottom-1.5 left-[7px] w-px bg-hairline" />
      {trace.map((t) => {
        const delta = t.tokens_before - t.tokens_after;
        return (
          <li key={t.stage} className="relative">
            <span
              aria-hidden
              className={cn(
                "absolute top-1 -left-6 size-[15px] rounded-full ring-4 ring-card",
                delta > 0 ? "bg-chart-after" : "bg-muted-foreground/40",
              )}
            />
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <span className="flex items-center gap-1.5 text-[13px] font-semibold">
                {STAGE_LABEL[t.stage] ?? t.stage}
                <Hint text={STAGE_HINT[t.stage]} />
              </span>
              <span className="text-[12px] text-muted-foreground tabular">
                {t.tokens_before > 0 && (
                  <>
                    {formatNumber(t.tokens_before)} to {formatNumber(t.tokens_after)}
                    {delta > 0 && <span className="ml-1.5 font-semibold text-savings">-{formatTokens(delta)}</span>}
                  </>
                )}
                <span className="ml-2 text-faint">{(t.ms ?? 0) < 1 ? "<1" : (t.ms ?? 0).toFixed(1)} ms</span>
              </span>
            </div>
            {(t.notes?.length ?? 0) > 0 && (
              <ul className="mt-1 space-y-0.5 text-[12px] leading-relaxed text-muted-foreground">
                {(t.notes ?? []).map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            )}
            {(t.items_removed ?? 0) > 0 && (
              <div className="mt-0.5 text-[11.5px] text-faint">{formatNumber(t.items_removed ?? 0)} items removed</div>
            )}
          </li>
        );
      })}
    </ol>
  );
}

const CATEGORY_LABEL: Record<string, string> = {
  history: "History",
  tool: "Tool output",
  documents: "Documents",
  summary: "Summary",
};

/** Adaptive budgeting: each category's weight, its share of the budget and what it used. */
export function AllocationView({ allocation }: { allocation: Allocation[] }) {
  const allocated = allocation.some((a) => a.budget > 0);
  return (
    <div className="space-y-3">
      {!allocated && (
        <p className="text-[12.5px] text-muted-foreground">
          Everything fit after cleaning, so no budget had to be split.
        </p>
      )}
      {allocation.map((a) => {
        const max = Math.max(a.budget, a.used, 1);
        return (
          <div key={a.category}>
            <div className="mb-1 flex items-baseline justify-between text-[12.5px]">
              <span className="font-medium">{CATEGORY_LABEL[a.category] ?? a.category}</span>
              <span className="text-muted-foreground tabular">
                weight {Math.round(a.weight * 100)}%
                {allocated && (
                  <>
                    <span className="mx-1.5 text-faint">|</span>
                    {formatNumber(a.used)} of {formatNumber(a.budget)}
                  </>
                )}
              </span>
            </div>
            <div className="relative h-2 rounded-full bg-muted" aria-hidden>
              {allocated && <div className="absolute inset-y-0 left-0 rounded-full bg-primary-soft" style={{ width: "100%" }} />}
              <div
                className="absolute inset-y-0 left-0 rounded-full bg-primary"
                style={{ width: `${allocated ? (100 * a.used) / max : 100 * a.weight}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function WarningsView({ warnings }: { warnings: OptimizeWarning[] }) {
  if (!warnings.length) {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-savings-soft px-3 py-2.5 text-[13px] text-savings">
        <CheckCircle2Icon className="size-4" />
        No warnings: budget met, structure valid, citations resolvable.
      </div>
    );
  }
  return (
    <ul className="space-y-2">
      {warnings.map((w) => (
        <li
          key={w.code}
          className={cn(
            "flex gap-2.5 rounded-lg px-3 py-2.5 text-[13px]",
            warningTone(w.code) === "warning" ? "bg-warning-soft" : "bg-muted",
          )}
        >
          <TriangleAlertIcon className={cn("mt-0.5 size-4 shrink-0", warningTone(w.code) === "warning" ? "text-warning" : "text-muted-foreground")} />
          <div className="min-w-0">
            <WarningChip code={w.code} />
            <p className="mt-1 leading-relaxed text-foreground/90">{w.message}</p>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function WarningCodes({ codes }: { codes: string[] }) {
  if (!codes.length) return <span className="text-[12px] text-faint">None</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {codes.map((c) => (
        <WarningChip key={c} code={c} />
      ))}
    </span>
  );
}
