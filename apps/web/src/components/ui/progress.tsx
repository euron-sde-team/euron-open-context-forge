import { cn } from "@/lib/cn";

/** Thin meter. Tone follows risk: primary below threshold, warning near, danger over. */
function Progress({
  value,
  tone = "primary",
  className,
  label,
}: {
  value: number;
  tone?: "primary" | "warning" | "danger" | "savings";
  className?: string;
  label?: string;
}) {
  const pct = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
  const bar = { primary: "bg-primary", warning: "bg-warning", danger: "bg-danger", savings: "bg-savings" }[tone];
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(pct)}
      aria-label={label}
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}
    >
      <div className={cn("h-full rounded-full transition-[width] duration-500", bar)} style={{ width: `${pct}%` }} />
    </div>
  );
}

export { Progress };
