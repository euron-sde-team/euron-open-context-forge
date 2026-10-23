import { cn } from "@/lib/cn";
import { formatNumber } from "@/lib/format";

/**
 * Before and after as two bars on one scale, so the reduction reads at a glance. The
 * optional budget is a tick on the same scale.
 */
export function TokenBar({
  before,
  after,
  budget,
  className,
  compact = false,
}: {
  before: number;
  after: number;
  budget?: number | null;
  className?: string;
  compact?: boolean;
}) {
  const max = Math.max(before, after, budget ?? 0, 1);
  const pct = (v: number) => `${Math.max(0.6, (v / max) * 100)}%`;
  return (
    <div className={cn("space-y-1.5", className)} aria-label={`${formatNumber(before)} tokens before, ${formatNumber(after)} after`}>
      {(["before", "after"] as const).map((k) => (
        <div key={k} className="flex items-center gap-2">
          {!compact && <span className="w-12 shrink-0 text-[11px] text-muted-foreground capitalize">{k}</span>}
          <div className="relative h-2 flex-1 rounded-full bg-muted">
            <div
              className={cn("absolute inset-y-0 left-0 rounded-full", k === "before" ? "bg-chart-before" : "bg-chart-after")}
              style={{ width: pct(k === "before" ? before : after) }}
            />
            {budget != null && (
              <div className="absolute -inset-y-1 w-px bg-foreground/50" style={{ left: pct(budget) }} title={`Budget ${formatNumber(budget)}`} />
            )}
          </div>
          {!compact && (
            <span className="w-16 shrink-0 text-right text-[11.5px] font-medium text-foreground tabular">
              {formatNumber(k === "before" ? before : after)}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
