import { formatNumber, formatPercent } from "@/lib/utils";

export function formatRateFraction(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return formatPercent(value * 100, digits);
}

export function formatOptionalNumber(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return formatNumber(value);
}

export function formatVph(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return formatNumber(Math.round(value));
}

/**
 * Breakout rate is meaningless when global pool N=0 — do not show 0% as poor performance.
 */
export function formatTopDecileBreakoutRate(
  rate: number | null | undefined,
  globalEligibleCount: number | null | undefined,
): string {
  if (globalEligibleCount === 0) {
    return "—";
  }
  return formatRateFraction(rate);
}

export {
  evidenceStatusLabel,
  lifecycleLabel,
} from "@/lib/design-system/labels";
