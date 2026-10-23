"use client";

import { CheckIcon } from "lucide-react";

import { cn } from "@/lib/cn";

/** Multi-select as a row of toggle pills, for short lists such as models. */
export function ToggleChips({
  options,
  value,
  onChange,
  ariaLabel,
  disabled,
}: {
  options: { value: string; label: string }[];
  value: string[];
  onChange: (value: string[]) => void;
  ariaLabel: string;
  disabled?: boolean;
}) {
  const set = new Set(value);
  return (
    <div role="group" aria-label={ariaLabel} className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const on = set.has(o.value);
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={on}
            disabled={disabled}
            onClick={() => onChange(on ? value.filter((v) => v !== o.value) : [...value, o.value])}
            className={cn(
              "inline-flex h-7 items-center gap-1 rounded-full bg-muted px-2.5 font-mono text-[12px] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50",
              on && "bg-primary-soft text-primary ring-1 ring-primary/40",
            )}
          >
            {on && <CheckIcon className="size-3" strokeWidth={3} />}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
