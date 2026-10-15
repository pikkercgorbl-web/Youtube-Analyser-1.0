import type { OutcomeCoverageCategory, OutcomeWindowPhase } from "./daily-intelligence-outcome-types";

export const OUTCOME_COVERAGE_CATEGORY_ORDER: OutcomeCoverageCategory[] = [
  "MEASURED_POST_SIGNAL",
  "MEASURED_PRE_SIGNAL",
  "NOT_MATURED",
  "MATURED_MISSING",
  "INVALID_TIMELINE",
  "INSUFFICIENT_EVIDENCE",
];

export function outcomeCoverageCategoryLabel(
  category: string,
  phase?: string | null,
): string {
  switch (category) {
    case "NOT_MATURED":
      if (phase === "not_yet_open") {
        return "Окно измерения ещё не открыто";
      }
      if (phase === "open_awaiting_measurement") {
        return "Ожидается измерение";
      }
      return "Outcome ещё не созрел";
    case "MEASURED_POST_SIGNAL":
      return "72h outcome измерен после edition signal";
    case "MEASURED_PRE_SIGNAL":
      return "Измерение получено до сигнала отчёта";
    case "MATURED_MISSING":
      return "Окно измерения закрыто, снимок не получен";
    case "INVALID_TIMELINE":
      return "Некорректная временная последовательность";
    case "INSUFFICIENT_EVIDENCE":
      return "Недостаточно исходных данных";
    default:
      return category;
  }
}

export function outcomeCoverageCategoryShortLabel(category: string): string {
  switch (category) {
    case "NOT_MATURED":
      return "Не созрел";
    case "MEASURED_POST_SIGNAL":
      return "Post-signal";
    case "MEASURED_PRE_SIGNAL":
      return "Pre-signal";
    case "MATURED_MISSING":
      return "Нет снимка";
    case "INVALID_TIMELINE":
      return "Timeline";
    case "INSUFFICIENT_EVIDENCE":
      return "Нет данных";
    default:
      return category;
  }
}

export function outcomeWindowPhaseLabel(phase: string): string {
  switch (phase) {
    case "not_yet_open":
      return "Окно ещё не открыто";
    case "open_awaiting_measurement":
      return "Ожидается измерение в окне";
    case "closed":
      return "Окно закрыто";
    case "not_applicable":
      return "—";
    default:
      return phase;
  }
}

export function attentionViewsSourceLabel(source: string): string {
  switch (source) {
    case "verified_snapshot":
      return "Подтверждённый snapshot (payload)";
    case "frozen_payload_unknown_source":
      return "Frozen views без доказанного времени измерения";
    case "fallback_unknown":
      return "Baseline отсутствует в payload";
    default:
      return source;
  }
}

export function metricsInterpretationLabel(value: string): string {
  switch (value) {
    case "descriptive_frozen_vs_horizon_outcome":
      return "Описательное сравнение frozen vs horizon outcome";
    case "verified_post_signal_growth_unavailable":
      return "Подтверждённый рост после signal недоступен (baseline не verified)";
    case "pre_signal_outcome_only":
      return "Outcome до edition signal — post-signal growth не применим";
    case "no_outcome_measurement":
      return "Нет валидного horizon outcome";
    case "insufficient_attention_baseline":
      return "Нет frozen baseline просмотров";
    default:
      return value;
  }
}

export function outcomeCoverageBadgeTone(category: string): string {
  switch (category) {
    case "MEASURED_POST_SIGNAL":
      return "border-emerald-500/40 bg-emerald-500/10 text-emerald-200";
    case "MEASURED_PRE_SIGNAL":
      return "border-sky-500/40 bg-sky-500/10 text-sky-100";
    case "NOT_MATURED":
      return "border-amber-500/40 bg-amber-500/10 text-amber-100";
    case "MATURED_MISSING":
      return "border-rose-500/40 bg-rose-500/10 text-rose-100";
    case "INVALID_TIMELINE":
      return "border-orange-500/40 bg-orange-500/10 text-orange-100";
    case "INSUFFICIENT_EVIDENCE":
      return "border-muted-foreground/30 bg-muted/30 text-muted-foreground";
    default:
      return "border-muted-foreground/30 bg-muted/30 text-muted-foreground";
  }
}
