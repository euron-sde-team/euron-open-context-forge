"use client";

import * as React from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { CHART, ChartLegend, ChartTooltipCard } from "@/components/charts/chart-tooltip";
import type { Point } from "@/lib/api/types";
import { formatNumber, formatPercent, formatTokens } from "@/lib/format";

const axisProps = {
  stroke: CHART.axis,
  tick: { fill: CHART.axis, fontSize: 11 },
  tickLine: false,
  axisLine: false,
} as const;

const dayFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const hourFmt = new Intl.DateTimeFormat("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
const longFmt = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** Tokens received vs tokens sent on, per bucket: the gap between the two is the saving. */
export default function TokensChart({ points, hourly }: { points: Point[]; hourly: boolean }) {
  const rows = React.useMemo(() => points.map((p) => ({ ...p, t: p.bucket })), [points]);
  const totals = rows.reduce(
    (a, r) => ({ before: a.before + r.tokens_before, after: a.after + r.tokens_after }),
    { before: 0, after: 0 },
  );
  const ticks = React.useMemo(() => {
    const step = Math.max(1, Math.ceil(rows.length / 7));
    return rows.filter((_, i) => i % step === 0).map((r) => r.t);
  }, [rows]);
  const fmt = (t: string) => (hourly ? hourFmt : dayFmt).format(new Date(t));

  return (
    <div className="flex flex-1 flex-col gap-3">
      <ChartLegend
        items={[
          { label: "Tokens received", color: CHART.before, value: formatTokens(totals.before) },
          { label: "Tokens sent on", color: CHART.after, value: formatTokens(totals.after) },
        ]}
      />
      <div className="min-h-[260px] w-full flex-1" role="img" aria-label="Tokens received and sent on over time">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={rows} margin={{ top: 6, right: 4, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="fill-before" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={CHART.before} stopOpacity={0.3} />
                <stop offset="100%" stopColor={CHART.before} stopOpacity={0.03} />
              </linearGradient>
              <linearGradient id="fill-after" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={CHART.after} stopOpacity={0.35} />
                <stop offset="100%" stopColor={CHART.after} stopOpacity={0.04} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke={CHART.grid} />
            <XAxis dataKey="t" ticks={ticks} tickFormatter={fmt} {...axisProps} minTickGap={16} />
            <YAxis tickFormatter={(v: number) => formatTokens(v)} width={48} {...axisProps} />
            <Tooltip
              cursor={{ stroke: CHART.axis, strokeDasharray: "3 3" }}
              content={({ active, payload }) => {
                const row = payload?.[0]?.payload as (Point & { t: string }) | undefined;
                if (!active || !row) return null;
                const pct = row.tokens_before ? (100 * row.tokens_saved) / row.tokens_before : 0;
                return (
                  <ChartTooltipCard
                    title={longFmt.format(new Date(row.t))}
                    rows={[
                      { label: "Received", value: formatNumber(row.tokens_before), color: CHART.before },
                      { label: "Sent on", value: formatNumber(row.tokens_after), color: CHART.after },
                    ]}
                    footer={`${formatNumber(row.runs)} runs, ${formatPercent(pct)} removed`}
                  />
                );
              }}
            />
            <Area
              type="monotone"
              dataKey="tokens_before"
              stroke={CHART.before}
              strokeWidth={2}
              fill="url(#fill-before)"
              activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }}
            />
            <Area
              type="monotone"
              dataKey="tokens_after"
              stroke={CHART.after}
              strokeWidth={2}
              fill="url(#fill-after)"
              activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
