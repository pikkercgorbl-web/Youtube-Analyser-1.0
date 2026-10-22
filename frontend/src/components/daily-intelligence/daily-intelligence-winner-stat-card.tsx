"use client";

import { cn } from "@/lib/utils";

export function DailyIntelligenceWinnerStatCard({
  label,
  value,
  hint,
  className,
}: {
  label: string;
  value: string;
  hint?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-border/80 bg-card/50 px-4 py-3 min-w-0",
        className,
      )}
    >
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums tracking-tight break-words">{value}</p>
      {hint ? <p className="mt-1 text-[11px] text-muted-foreground leading-snug">{hint}</p> : null}
    </div>
  );
}
