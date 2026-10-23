"use client";

import { ActivityIcon, FlaskConicalIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { AllocationView, TraceView, WarningCodes } from "@/components/engine-views";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { PageHeader } from "@/components/page-header";
import { SourceChip, StrategyChip } from "@/components/status-chip";
import { Surface } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { TokenBar } from "@/components/token-bar";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { SimpleSelect } from "@/components/ui/select";
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Run } from "@/lib/api/types";
import { retentionTone, SOURCES, WORKLOADS, workloadLabel } from "@/lib/chips";
import { formatDateTime, formatLatency, formatNumber, formatPercent, formatRelative, formatUsd } from "@/lib/format";

import { useRun, useRuns, type RunFilters } from "../api";

function reduction(r: Pick<Run, "tokens_before" | "tokens_after">): number {
  return r.tokens_before ? (100 * (r.tokens_before - r.tokens_after)) / r.tokens_before : 0;
}

function Retention({ retained, total }: { retained: number; total: number }) {
  if (!total) return <span className="text-[12px] text-faint">No facts</span>;
  return (
    <Chip tone={retentionTone(retained / total)}>
      {retained}/{total}
    </Chip>
  );
}

function Stat({ label, children, hint }: { label: string; children: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="rounded-lg bg-muted/70 px-3 py-2.5">
      <div className="flex items-center gap-1 text-[11.5px] text-muted-foreground">
        {label}
        {hint}
      </div>
      <div className="mt-0.5 text-[15px] font-semibold tabular">{children}</div>
    </div>
  );
}

function RunDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const run = useRun(id);
  const r = run.data;
  return (
    <Sheet open={id != null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Run {id}</SheetTitle>
          <SheetDescription>{r ? `${formatDateTime(r.created_at)}, ${r.key_name ?? "no key"}` : "Loading"}</SheetDescription>
        </SheetHeader>
        <SheetBody className="space-y-6">
          {run.isError && <ErrorState error={run.error} compact onRetry={() => void run.refetch()} />}
          {!r && !run.isError && <Skeleton className="h-64 w-full" />}
          {r && (
            <>
              <div className="flex flex-wrap gap-1.5">
                <SourceChip value={r.source} />
                <StrategyChip value={r.strategy} />
                <Chip tone="neutral">{workloadLabel(r.workload)}</Chip>
                {r.profile && r.profile !== r.workload && <Chip tone="primary">profile {r.profile}</Chip>}
                <Chip tone={r.exact ? "success" : "info"}>{r.exact ? r.tokenizer : `${r.tokenizer}`}</Chip>
                {r.cache_hit && <Chip tone="savings">Result cache hit</Chip>}
              </div>
              <TokenBar before={r.tokens_before} after={r.tokens_after} budget={r.budget} />
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                <Stat label="Reduction">{formatPercent(reduction(r))}</Stat>
                <Stat label="Budget">{r.budget ? `${formatNumber(r.budget)} ${r.budget_met ? "met" : "missed"}` : "None"}</Stat>
                <Stat label="Facts kept" hint={<Hint term="factRetention" />}>
                  {r.facts_total ? `${r.facts_retained} of ${r.facts_total}` : "n/a"}
                </Stat>
                <Stat label="Messages">
                  {r.messages_in} to {r.messages_out}
                </Stat>
                <Stat label="Documents">
                  {r.documents_in} to {r.documents_out}
                </Stat>
                <Stat label="Engine time">{formatLatency(r.latency_ms)}</Stat>
                <Stat label="Cost avoided (est.)" hint={<Hint term="costAvoided" />}>
                  {r.cost_avoided_usd != null ? formatUsd(r.cost_avoided_usd) : "Unpriced"}
                </Stat>
                <Stat label="Citations">{r.documents_in ? (r.citations_preserved ? "All resolve" : "Problems") : "n/a"}</Stat>
                <Stat label="Summary">{r.summary_tokens ? `${formatNumber(r.summary_tokens)} tokens` : "None"}</Stat>
              </div>
              {r.upstream && (
                <section>
                  <h3 className="mb-2 text-[13px] font-semibold">Forwarded upstream</h3>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                    <Stat label="Upstream">{r.upstream}</Stat>
                    <Stat label="Model">{r.upstream_model ?? "n/a"}</Stat>
                    <Stat label="Status">{r.upstream_status ?? "n/a"}</Stat>
                    <Stat label="Upstream cost">{r.upstream_cost_usd != null ? formatUsd(r.upstream_cost_usd) : "Not reported"}</Stat>
                  </div>
                </section>
              )}
              <section>
                <h3 className="mb-2 text-[13px] font-semibold">Warnings</h3>
                <WarningCodes codes={r.warnings} />
              </section>
              <section>
                <h3 className="mb-3 flex items-center gap-1.5 text-[13px] font-semibold">
                  Budget allocation <Hint term="allocation" />
                </h3>
                <AllocationView allocation={r.allocation} />
              </section>
              <section>
                <h3 className="mb-3 text-[13px] font-semibold">Pipeline trace</h3>
                <TraceView trace={r.trace} />
              </section>
            </>
          )}
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}

export function RunsScreen() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [filters, setFilters] = React.useState<RunFilters>({});
  const runs = useRuns(filters);
  const items = runs.data?.pages.flatMap((p) => p.items) ?? [];
  const openId = params.get("run") ? Number(params.get("run")) : null;
  const open = (id: number | null) => router.replace(id == null ? pathname : `${pathname}?run=${id}`, { scroll: false });
  const filtered = !!(filters.source || filters.workload || filters.budget_missed);

  return (
    <>
      <PageHeader
        title="Runs"
        description="Every optimization: tokens before and after, the facts it kept, and the trace of each pipeline stage."
      />
      <Surface>
        <div className="flex flex-wrap items-center gap-2 px-4 py-3">
          <SimpleSelect
            aria-label="Source"
            size="sm"
            className="w-36"
            value={filters.source ?? "all"}
            onValueChange={(v) => setFilters((f) => ({ ...f, source: v === "all" ? undefined : v }))}
            options={[{ value: "all", label: "All sources" }, ...SOURCES.map((s) => ({ value: s, label: s === "api" ? "API" : s.charAt(0).toUpperCase() + s.slice(1) }))]}
          />
          <SimpleSelect
            aria-label="Workload"
            size="sm"
            className="w-40"
            value={filters.workload ?? "all"}
            onValueChange={(v) => setFilters((f) => ({ ...f, workload: v === "all" ? undefined : v }))}
            options={[{ value: "all", label: "All workloads" }, ...WORKLOADS.map((w) => ({ value: w, label: workloadLabel(w) }))]}
          />
          <label className="ml-1 flex items-center gap-2 text-[13px] text-muted-foreground">
            <Switch
              checked={!!filters.budget_missed}
              onCheckedChange={(v) => setFilters((f) => ({ ...f, budget_missed: v }))}
              aria-label="Only runs that missed the budget"
            />
            Budget missed only
          </label>
          {filtered && (
            <Button variant="subtle" size="xs" onClick={() => setFilters({})}>
              Clear filters
            </Button>
          )}
        </div>
        {runs.isError && !items.length ? (
          <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />
        ) : runs.isLoading ? (
          <div className="px-4 pb-4">
            <TableSkeleton rows={8} cols={7} />
          </div>
        ) : items.length === 0 ? (
          filtered ? (
            <EmptyState
              icon={ActivityIcon}
              title="No runs match these filters"
              description="Nothing was recorded with this source, workload or budget outcome yet."
              action={
                <Button variant="outline" onClick={() => setFilters({})}>
                  Clear filters
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon={FlaskConicalIcon}
              title="No runs recorded yet"
              description="Each call to the API, the proxy or the playground appears here with its stats and trace. Content is never stored unless STORE_CONTENT is on."
              action={
                <Button nativeButton={false} render={<Link href="/playground" />}>
                  Try the playground
                </Button>
              }
            />
          )
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Workload</TableHead>
                  <TableHead className="hidden md:table-cell">Source</TableHead>
                  <TableHead className="hidden lg:table-cell">Model</TableHead>
                  <TableHead className="w-48">Tokens</TableHead>
                  <TableHead className="text-right">Reduction</TableHead>
                  <TableHead className="hidden sm:table-cell">Facts</TableHead>
                  <TableHead className="hidden xl:table-cell">Warnings</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((r) => (
                  <TableRow
                    key={r.id}
                    tabIndex={0}
                    className="cursor-pointer"
                    onClick={() => open(r.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        open(r.id);
                      }
                    }}
                  >
                    <TableCell className="whitespace-nowrap text-muted-foreground tabular" title={formatDateTime(r.created_at)}>
                      {formatRelative(r.created_at)}
                    </TableCell>
                    <TableCell className="font-medium">{workloadLabel(r.workload)}</TableCell>
                    <TableCell className="hidden md:table-cell">
                      <SourceChip value={r.source} />
                    </TableCell>
                    <TableCell className="hidden max-w-40 truncate font-mono text-[12px] lg:table-cell">{r.model}</TableCell>
                    <TableCell>
                      <TokenBar before={r.tokens_before} after={r.tokens_after} budget={r.budget} compact />
                      <div className="mt-1 text-[11px] text-muted-foreground tabular">
                        {formatNumber(r.tokens_before)} to {formatNumber(r.tokens_after)}
                      </div>
                    </TableCell>
                    <TableCell className="text-right font-semibold tabular">
                      <span className={r.budget_met ? "text-foreground" : "text-warning"}>{formatPercent(reduction(r))}</span>
                    </TableCell>
                    <TableCell className="hidden sm:table-cell">
                      <Retention retained={r.facts_retained} total={r.facts_total} />
                    </TableCell>
                    <TableCell className="hidden xl:table-cell">
                      <WarningCodes codes={r.warnings} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {runs.hasNextPage && (
              <div className="flex justify-center py-4">
                <Button variant="outline" size="sm" onClick={() => void runs.fetchNextPage()} disabled={runs.isFetchingNextPage}>
                  {runs.isFetchingNextPage ? "Loading..." : "Load older runs"}
                </Button>
              </div>
            )}
          </>
        )}
      </Surface>
      <RunDrawer id={openId} onClose={() => open(null)} />
    </>
  );
}
