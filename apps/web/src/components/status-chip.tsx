"use client";

import { Chip } from "@/components/ui/chip";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  jobChip,
  kindChip,
  sourceChip,
  strategyChip,
  warningLabel,
  warningTone,
  type ChipSpec,
} from "@/lib/chips";

export function SpecChip({ spec, withHint = true, dot = true }: { spec: ChipSpec; withHint?: boolean; dot?: boolean }) {
  const chip = (
    <Chip tone={spec.tone} dot={dot}>
      {spec.label}
    </Chip>
  );
  if (!withHint || !spec.hint) return chip;
  return (
    <Tooltip>
      <TooltipTrigger render={<span tabIndex={0} className="inline-flex rounded-full focus-visible:outline-2 focus-visible:outline-ring" />}>
        {chip}
      </TooltipTrigger>
      <TooltipContent>{spec.hint}</TooltipContent>
    </Tooltip>
  );
}

export const SourceChip = ({ value }: { value: string }) => <SpecChip spec={sourceChip(value)} dot={false} />;
export const StrategyChip = ({ value }: { value: string }) => <SpecChip spec={strategyChip(value)} dot={false} />;
export const JobChip = ({ value }: { value: string }) => <SpecChip spec={jobChip(value)} />;
export const KindChip = ({ value }: { value: string }) => <SpecChip spec={kindChip(value)} dot={false} />;

export function WarningChip({ code }: { code: string }) {
  return (
    <Chip tone={warningTone(code)} dot>
      {warningLabel(code)}
    </Chip>
  );
}
