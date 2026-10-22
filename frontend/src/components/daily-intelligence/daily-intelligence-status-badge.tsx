"use client";

import { dailyIntelligenceStatusLabel } from "@/lib/daily-intelligence-labels";
import { cn } from "@/lib/utils";

export function DailyIntelligenceStatusBadge({
  status,
  title,
}: {
  status: string;
  title?: string;
}) {
  const tone =
    status === "complete"
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
      : status === "partial"
        ? "border-amber-500/40 bg-amber-500/10 text-amber-100"
        : status === "provisional"
          ? "border-sky-500/40 bg-sky-500/10 text-sky-100"
          : "border-muted-foreground/30 bg-muted/30 text-muted-foreground";
  return (
    <span
      className={cn("inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium", tone)}
      title={title}
      data-testid="di-report-status"
    >
      {dailyIntelligenceStatusLabel(status)}
    </span>
  );
}
