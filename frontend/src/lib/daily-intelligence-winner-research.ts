import { formatWinnerMetrics } from "@/lib/daily-intelligence-evidence-format";
import { outcomeCoverageCategoryLabel } from "@/lib/daily-intelligence-outcome-labels";
import type { DailyIntelligenceWinnerOutcomeFollowUp } from "@/lib/daily-intelligence-outcome-types";

export type WinnerMetricsFormatted = ReturnType<typeof formatWinnerMetrics>;

export function buildAttentionSummaryParagraph(
  metrics: WinnerMetricsFormatted,
  humanReasons: string[],
): string {
  const parts: string[] = [];
  if (humanReasons.length > 0) {
    parts.push(humanReasons.slice(0, 2).join(". "));
  }
  const stats: string[] = [];
  if (metrics.views !== "Нет данных") {
    stats.push(`на момент подборки было ${metrics.views} просмотров`);
  }
  if (metrics.vph !== "Нет данных") {
    stats.push(`темп ${metrics.vph} (просмотров в час)`);
  }
  if (metrics.ageHours !== "Нет данных") {
    stats.push(`возраст видео ${metrics.ageHours}`);
  }
  if (metrics.breakoutRank !== "Нет данных") {
    stats.push(`место в breakout ${metrics.breakoutRank}`);
  }
  if (stats.length > 0) {
    parts.push(`По сохранённым данным Attention: ${stats.join("; ")}.`);
  }
  if (parts.length === 0) {
    return "Radar зафиксировал видео в подборке, но в архиве мало текстовых пояснений — см. технические доказательства.";
  }
  return parts.join(" ");
}

export type OutcomeResearchCopy = {
  headline: string;
  explanation: string;
  nextStep: string;
  tone: "success" | "info" | "pending" | "muted" | "warning";
};

export function outcomeResearchCopy(
  category: string,
  phase?: string | null,
): OutcomeResearchCopy {
  switch (category) {
    case "MEASURED_POST_SIGNAL":
      return {
        headline: "Контрольное измерение после подборки есть",
        explanation: outcomeCoverageCategoryLabel(category, phase),
        nextStep:
          "Можно сравнить просмотры на момент подборки с horizon snapshot. Это не прогноз будущего успеха.",
        tone: "success",
      };
    case "MEASURED_PRE_SIGNAL":
      return {
        headline: "Снимок просмотров получен раньше финальной подборки дня",
        explanation: outcomeCoverageCategoryLabel(category, phase),
        nextStep:
          "Post-signal рост не считается — измерение относится к периоду до edition signal.",
        tone: "info",
      };
    case "NOT_MATURED":
      if (phase === "not_yet_open") {
        return {
          headline: "Окно контрольного измерения ещё не открыто",
          explanation: "С момента discovery ещё не прошло достаточно времени для horizon outcome (≈72h ±12h).",
          nextStep: "Вернитесь позже или сохраните видео в исследование, чтобы не потерять контекст.",
          tone: "pending",
        };
      }
      return {
        headline: "Ожидается контрольное измерение",
        explanation: "Окно horizon outcome открыто, но подходящий snapshot в архиве пока не найден.",
        nextStep: "Это нормальное ожидание, а не ошибка системы.",
        tone: "pending",
      };
    case "MATURED_MISSING":
      return {
        headline: "Контрольное измерение не получено",
        explanation: outcomeCoverageCategoryLabel(category, phase),
        nextStep: "Итог по horizon outcome для этого видео в архиве отсутствует.",
        tone: "warning",
      };
    case "INVALID_TIMELINE":
      return {
        headline: "Временная цепочка не сходится",
        explanation: outcomeCoverageCategoryLabel(category, phase),
        nextStep: "Не опирайтесь на автоматические delta-метрики — проверьте технические доказательства.",
        tone: "warning",
      };
    case "INSUFFICIENT_EVIDENCE":
      return {
        headline: "Недостаточно данных для контрольного сравнения",
        explanation: outcomeCoverageCategoryLabel(category, phase),
        nextStep: "Оценивайте видео по frozen evidence подборки; outcome follow-up ограничен.",
        tone: "muted",
      };
    default:
      return {
        headline: category,
        explanation: "",
        nextStep: "",
        tone: "muted",
      };
  }
}

export function outcomeComparisonLimitationNote(
  followUp: DailyIntelligenceWinnerOutcomeFollowUp,
): string | null {
  const prov = followUp.attention_views_provenance;
  if (prov.baseline_provenance_verified) {
    return null;
  }
  if (
    followUp.coverage_category === "MEASURED_POST_SIGNAL" ||
    followUp.comparison_metrics.delta_views_descriptive != null
  ) {
    return "Сравнение двух сохранённых значений просмотров. Точное время первого измерения не подтверждено.";
  }
  return null;
}

export const OUTCOME_TONE_CLASS: Record<OutcomeResearchCopy["tone"], string> = {
  success: "border-emerald-500/35 bg-emerald-500/10",
  info: "border-sky-500/35 bg-sky-500/10",
  pending: "border-amber-500/35 bg-amber-500/10",
  warning: "border-rose-500/35 bg-rose-500/10",
  muted: "border-border bg-card/40",
};
