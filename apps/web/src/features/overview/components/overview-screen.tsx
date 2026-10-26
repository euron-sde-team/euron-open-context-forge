"use client";

import {
  CheckCheckIcon,
  CoinsIcon,
  FlaskConicalIcon,
  GaugeIcon,
  ScissorsIcon,
  ShieldCheckIcon,
  TimerIcon,
  ZapIcon,
} from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { KpiTile } from "@/components/kpi-tile";
import { PageHeader } from "@/components/page-header";
import { Segmented } from "@/components/segmented";
import { SourceChip } from "@/components/status-chip";
import { Surface, SurfaceHeader } from "@/components/surface";
import { TokenBar } from "@/components/token-bar";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useRuns } from "@/features/runs/api";
import type { Breakdown, Overview } from "@/lib/api/types";
import { workloadLabel } from "@/lib/chips";
import { formatLatency, formatNumber, formatPercent, formatRatio, formatRelative, formatTokens, formatUsd } from "@/lib/format";
import { DAY_OPTIONS, useUiPrefs, type Days } from "@/lib/store";

import { useOverview } from "../api";

const TokensChart = dynamic(() => import("./tokens-chart"), {
  ssr: false,
  loading: () => <Skeleton className="h-[290px] w-full" />,
});

function BreakdownList({ rows, label }: { rows: Breakdown[]; label: (k: string) => string }) {
  if (!rows.length) {
    return <p className="px-5 pb-5 text-[13px] text-muted-foreground">No runs in this period yet.</p>;
  }
  const max = Math.max(...rows.map((r) => r.tokens_before), 1);
  return (
    <ul className="space-y-3 px-5 pb-5">
      {rows.map((r) => (
        <li key={r.key}>
          <div className="mb-1 flex items-baseline justify-between gap-3 text-[13px]">
            <span className="truncate font-medium">{label(r.key)}</span>
            <span className="shrink-0 text-muted-foreground tabular">
              {formatTokens(r.tokens_before - r.tokens_after)} saved
              <span className="ml-2 font-semibold text-savings">{formatPercent(r.reduction_percent)}</span>
            </span>
          </div>
          <div className="relative h-2 rounded-full bg-muted" aria-hidden>
            <div className="absolute inset-y-0 left-0 rounded-full bg-chart-before" style={{ width: `${(100 * r.tokens_before) / max}%` }} />
            <div className="absolute inset-y-0 left-0 rounded-full bg-chart-after" style={{ width: `${(100 * r.tokens_after) / max}%` }} />
          </div>
          <div className="mt-1 text-[11.5px] text-muted-foreground">{formatNumber(r.runs)} runs</div>
        </li>
      ))}
    </ul>
  );
}

function RecentRuns() {
  const runs = useRuns({}, 6);
  const items = runs.data?.pages[0]?.items ?? [];
  return (
    <Surface className="flex flex-col">
      <SurfaceHeader
        title="Latest runs"
        description="The newest optimizations, live"
        action={
          <Button variant="subtle" size="xs" nativeButton={false} render={<Link href="/runs" />}>
            All runs
          </Button>
        }
      />
      {runs.isLoading ? (
        <div className="space-y-3 px-5 pb-5">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : runs.isError && !runs.data ? (
        <ErrorState compact error={runs.error} onRetry={() => void runs.refetch()} />
      ) : items.length === 0 ? (
        <p className="px-5 pb-5 text-[13px] text-muted-foreground">Runs appear here as soon as something calls the API.</p>
      ) : (
        <ul className="divide-y divide-hairline px-5 pb-3">
          {items.map((r) => (
            <li key={r.id}>
              <Link
                href={`/runs?run=${r.id}`}
                className="-mx-2 grid grid-cols-[1fr_auto] items-center gap-3 rounded-lg px-2 py-2.5 hover:bg-muted/60 focus-visible:outline-2 focus-visible:outline-ring"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-[13px] font-medium">
                    <span className="truncate">{workloadLabel(r.workload)}</span>
                    <SourceChip value={r.source} />
                  </div>
                  <TokenBar before={r.tokens_before} after={r.tokens_after} budget={r.budget} compact className="mt-1.5 max-w-60" />
                </div>
                <div className="text-right text-[12px] text-muted-foreground tabular">
                  <div className="font-semibold text-foreground">
                    {formatPercent(r.tokens_before ? (100 * (r.tokens_before - r.tokens_after)) / r.tokens_before : 0)}
                  </div>
                  {formatRelative(r.created_at)}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Surface>
  );
}

function Kpis({ data, days }: { data: Overview | undefined; days: number }) {
  const p = data?.previous ?? {};
  const cmp = `vs previous ${days === 1 ? "24 hours" : `${days} days`}`;
  const loading = !data;
  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      <KpiTile
        label="Tokens saved"
        icon={ScissorsIcon}
        hint="tokensSaved"
        value={formatTokens(data?.tokens_saved)}
        current={data?.tokens_saved}
        previous={p.tokens_saved}
        comparison={cmp}
        accent="savings"
        loading={loading}
      />
      <KpiTile
        label="Reduction"
        icon={GaugeIcon}
        hint="reduction"
        value={formatPercent(data?.reduction_percent)}
        current={data?.reduction_percent}
        previous={p.reduction_percent}
        comparison={cmp}
        loading={loading}
      />
      <KpiTile
        label="Fact retention"
        icon={ShieldCheckIcon}
        hint="factRetention"
        value={formatRatio(data?.fact_retention)}
        current={data?.fact_retention}
        previous={p.fact_retention}
        comparison={cmp}
        accent="savings"
        loading={loading}
      />
      <KpiTile
        label="Cost avoided (est.)"
        icon={CoinsIcon}
        hint="costAvoided"
        value={formatUsd(data?.cost_avoided)}
        current={data?.cost_avoided}
        previous={p.cost_avoided}
        comparison={cmp}
        accent="savings"
        loading={loading}
      />
      <KpiTile
        label="Runs"
        icon={ZapIcon}
        value={formatNumber(data?.runs)}
        current={data?.runs}
        previous={p.runs}
        goodWhen="neutral"
        comparison={cmp}
        loading={loading}
      />
      <KpiTile
        label="Budget met"
        icon={CheckCheckIcon}
        hint="budgetMet"
        value={formatRatio(data?.budget_met_rate)}
        current={data?.budget_met_rate}
        previous={p.budget_met_rate}
        comparison={cmp}
        loading={loading}
      />
      <KpiTile
        label="Result cache hits"
        icon={ZapIcon}
        hint="cacheHit"
        value={formatRatio(data?.cache_hit_rate)}
        current={data?.cache_hit_rate}
        previous={p.cache_hit_rate}
        goodWhen="neutral"
        comparison={cmp}
        loading={loading}
      />
      <KpiTile
        label="Avg engine latency"
        icon={TimerIcon}
        value={formatLatency(data?.avg_latency_ms)}
        current={data?.avg_latency_ms}
        previous={p.avg_latency_ms}
        goodWhen="down"
        comparison={cmp}
        accent="warning"
        loading={loading}
      />
    </div>
  );
}

export function OverviewScreen() {
  const days = useUiPrefs((s) => s.days);
  const setDays = useUiPrefs((s) => s.setDays);
  const overview = useOverview(days);
  const data = overview.data;

  const header = (
    <PageHeader
      title="Overview"
      description="How much context ContextForge removed, and how much of what mattered it kept."
      actions={
        <Segmented<string>
          ariaLabel="Period"
          value={String(days)}
          onChange={(v) => setDays(Number(v) as Days)}
          options={DAY_OPTIONS.map((d) => ({ value: String(d), label: d === 1 ? "24h" : `${d}d` }))}
          className="w-48"
        />
      }
    />
  );

  if (overview.isError && !data) {
    return (
      <>
        {header}
        <Surface>
          <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />
        </Surface>
      </>
    );
  }

  if (data && data.runs === 0 && (data.previous.runs ?? 0) === 0) {
    return (
      <>
        {header}
        <Surface>
          <EmptyState
            icon={FlaskConicalIcon}
            title="No optimizations yet"
            description="Every call to /v1/context/optimize, the OpenAI-compatible proxy or the playground is recorded here with its before and after token counts and the facts it kept. Try a sample in the playground to see it work."
            action={
              <Button nativeButton={false} render={<Link href="/playground" />}>
                <FlaskConicalIcon />
                Open the playground
              </Button>
            }
          />
        </Surface>
      </>
    );
  }

  return (
    <>
      {header}
      <div className="space-y-4">
        <Kpis data={data} days={days} />
        <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <Surface className="flex flex-col">
            <SurfaceHeader
              title="Tokens received vs sent on"
              titleExtra={<Hint term="tokensSaved" />}
              description="The gap between the two lines is context that never reached a model"
            />
            <div className="flex flex-1 px-5 pb-5">
              {data ? <TokensChart points={data.series} hourly={days === 1} /> : <Skeleton className="h-[290px] w-full" />}
            </div>
          </Surface>
          <RecentRuns />
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          <Surface>
            <SurfaceHeader title="By workload" titleExtra={<Hint term="workload" />} description="Detected or requested profile" />
            {data ? <BreakdownList rows={data.by_workload} label={workloadLabel} /> : <Skeleton className="mx-5 mb-5 h-40" />}
          </Surface>
          <Surface>
            <SurfaceHeader title="By source" description="Library, API, proxy or background job" />
            {data ? (
              <BreakdownList rows={data.by_source} label={(k) => ({ api: "API", proxy: "Proxy", job: "Jobs", playground: "Playground" })[k] ?? k} />
            ) : (
              <Skeleton className="mx-5 mb-5 h-40" />
            )}
          </Surface>
          <Surface>
            <SurfaceHeader title="By model" description="Counted with each model's tokenizer" />
            {data ? <BreakdownList rows={data.by_model} label={(k) => k} /> : <Skeleton className="mx-5 mb-5 h-40" />}
          </Surface>
        </div>
      </div>
    </>
  );
}
