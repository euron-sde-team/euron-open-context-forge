"use client";

import { useId } from "react";

import { cn } from "@/lib/cn";

/** The ContextForge mark: three bars of context narrowing into one bright spark. */
export function ForgeMark({ className }: { className?: string }) {
  // A unique gradient id per instance: when the first SVG defining a shared id sits in a
  // hidden subtree (the collapsed sidebar on phones), browsers resolve the fill to nothing.
  const gradient = `cf-mark-${useId().replace(/:/g, "")}`;
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={cn("size-7 shrink-0", className)}>
      <defs>
        <linearGradient id={gradient} x1="4" y1="3" x2="28" y2="29" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="var(--chart-after)" />
          <stop offset="1" stopColor="var(--primary)" />
        </linearGradient>
      </defs>
      <rect x="2.5" y="2.5" width="27" height="27" rx="8" fill={`url(#${gradient})`} />
      <rect x="7.5" y="9" width="17" height="3" rx="1.5" fill="white" fillOpacity="0.55" />
      <rect x="7.5" y="14.5" width="12" height="3" rx="1.5" fill="white" fillOpacity="0.75" />
      <rect x="7.5" y="20" width="7" height="3" rx="1.5" fill="white" />
      <circle cx="21.5" cy="21.5" r="2.4" fill="white" />
    </svg>
  );
}

export function ForgeLogo({ className, collapsed = false }: { className?: string; collapsed?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <ForgeMark />
      {!collapsed && <span className="text-[15px] font-semibold tracking-[-0.02em] text-foreground">ContextForge</span>}
    </span>
  );
}
