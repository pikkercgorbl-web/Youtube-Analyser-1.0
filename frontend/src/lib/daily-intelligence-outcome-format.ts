import { formatOptionalViews } from "@/lib/attention-format";
import { formatDateTimeLocal } from "@/lib/monitoring-format";

import type { DailyIntelligenceComparisonMetrics } from "./daily-intelligence-outcome-types";

export function formatOutcomeNullableViews(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return formatOptionalViews(value) ?? "—";
}

export function formatOutcomeNullableDelta(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toLocaleString("ru-RU")}`;
}

export function formatOutcomeNullableRatio(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return `×${value.toFixed(3)}`;
}

export function formatOutcomeTimestamp(value: unknown): string {
  if (typeof value !== "string" || !value) {
    return "—";
  }
  return formatDateTimeLocal(value);
}

export function formatComparisonMetricsBlock(metrics: DailyIntelligenceComparisonMetrics) {
  return {
    frozenViews: formatOutcomeNullableViews(metrics.views_at_attention_frozen),
    outcomeViews: formatOutcomeNullableViews(metrics.views_at_outcome_horizon),
    deltaDescriptive: formatOutcomeNullableDelta(metrics.delta_views_descriptive),
    ratioDescriptive: formatOutcomeNullableRatio(metrics.descriptive_growth_ratio),
    verifiedGrowth: formatOutcomeNullableDelta(metrics.verified_post_signal_growth),
    verifiedRatio: formatOutcomeNullableRatio(metrics.verified_post_signal_growth_ratio),
    elapsedHours:
      metrics.elapsed_hours_edition_signal_to_outcome != null
        ? `${metrics.elapsed_hours_edition_signal_to_outcome} ч`
        : "—",
  };
}
