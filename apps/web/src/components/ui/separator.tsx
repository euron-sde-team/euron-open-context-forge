import { cn } from "@/lib/cn";

function Separator({ className, vertical = false }: { className?: string; vertical?: boolean }) {
  return (
    <div
      role="separator"
      aria-orientation={vertical ? "vertical" : "horizontal"}
      className={cn("shrink-0 bg-hairline", vertical ? "h-full w-px" : "h-px w-full", className)}
    />
  );
}

export { Separator };
