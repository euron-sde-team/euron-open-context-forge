"use client";

import { InfoIcon } from "lucide-react";
import * as React from "react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { GLOSSARY, type GlossaryKey } from "@/lib/glossary";

/** A small (i) that explains a term on hover or keyboard focus. */
export function Hint({ term, text, className }: { term?: GlossaryKey; text?: React.ReactNode; className?: string }) {
  const content = text ?? (term ? GLOSSARY[term] : null);
  if (!content) return null;
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            aria-label="What does this mean?"
            className={cn(
              "inline-flex size-4 shrink-0 items-center justify-center rounded-full text-faint transition-colors hover:text-muted-foreground focus-visible:text-foreground focus-visible:outline-none",
              className,
            )}
          />
        }
      >
        <InfoIcon className="size-3.5" />
      </TooltipTrigger>
      <TooltipContent>{content}</TooltipContent>
    </Tooltip>
  );
}
