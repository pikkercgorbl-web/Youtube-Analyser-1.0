"use client";

import {
  outcomeCoverageBadgeTone,
  outcomeCoverageCategoryLabel,
  outcomeCoverageCategoryShortLabel,
} from "@/lib/daily-intelligence-outcome-labels";
import { cn } from "@/lib/utils";

export function DailyIntelligenceOutcomeCoverageBadge({
  category,
  phase,
  compact,
}: {
  category: string;
  phase?: string | null;
  compact?: boolean;
}) {
  const title = outcomeCoverageCategoryLabel(category, phase);
  const label = compact ? outcomeCoverageCategoryShortLabel(category) : title;
  return (
    <span
      className={cn(
        "inline-flex max-w-[140px] rounded-full border px-2 py-0.5 text-[11px] font-medium leading-snug",
        outcomeCoverageBadgeTone(category),
      )}
      title={compact ? title : undefined}
      data-testid="di-outcome-coverage-badge"
      data-category={category}
    >
      {label}
    </span>
  );
}
