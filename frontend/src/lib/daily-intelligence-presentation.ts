import { humanReasonsForDisplay } from "@/lib/attention-format";
import { formatWinnerMetrics } from "@/lib/daily-intelligence-evidence-format";
import type { DailyIntelligenceReportSummary } from "@/lib/daily-intelligence-types";
import { formatDateTimeLocal, formatDateTimeUtc } from "@/lib/monitoring-format";

import type { WinnerInsightBlock } from "@/lib/opportunity-winner-presentation";

export function buildReportDiscoverySummary(
  report: DailyIntelligenceReportSummary,
): string {
  const winners = report.winner_count;
  const families = report.family_count;
  const wText = winners != null ? `${winners} видео` : "видео";
  const fText =
    families != null
      ? families === 0
        ? "тем в подборке нет"
        : `${families} тем (pattern families)`
      : "тем";
  return `В этом выпуске зафиксированы ${wText} и ${fText} по снимку Attention на момент публикации — не текущие показатели YouTube.`;
}

export function formatReportAnalyzedPeriod(report: DailyIntelligenceReportSummary): string {
  if (report.source_window_start && report.source_window_end) {
    return `${formatDateTimeUtc(report.source_window_start)} — ${formatDateTimeUtc(report.source_window_end)}`;
  }
  if (report.source_window_hours != null) {
    return `последние ${report.source_window_hours} ч окна Attention (UTC)`;
  }
  return "период окна не сохранён в архиве";
}

export function formatReportGeneratedLine(report: DailyIntelligenceReportSummary): string {
  const parts: string[] = [];
  if (report.generated_at) {
    parts.push(`Отчёт сформирован ${formatDateTimeUtc(report.generated_at)}`);
  }
  if (report.source_computed_at) {
    parts.push(`снимок Attention ${formatDateTimeUtc(report.source_computed_at)}`);
  }
  return parts.join(" · ") || "Время формирования не указано";
}

/** Why the video is in this frozen daily edition (payload_json only). */
export function buildDiWinnerWhyInReport(
  evidence: Record<string, unknown>,
  editionRank: number,
): WinnerInsightBlock {
  const codes = new Set((evidence.reason_codes as string[] | undefined) ?? []);
  const metrics = formatWinnerMetrics(evidence);
  const human = humanReasonsForDisplay(
    (evidence.human_reasons as string[] | undefined) ?? [],
  );

  if (codes.has("breakout_high_rank") && evidence.breakout_rank != null) {
    return {
      key: "why",
      label: "Почему в отчёте",
      short: `Место №${editionRank}`,
      detail:
        human[0] ??
        `Radar rank #${evidence.breakout_rank} в окне Attention на момент публикации.`,
    };
  }
  if (codes.has("high_current_vph") && metrics.vph !== "Нет данных") {
    return {
      key: "why",
      label: "Почему в отчёте",
      short: "VPH в топ‑25%",
      detail: human[0] ?? `Темп ${metrics.vph} среди eligible видео окна (сохранённый снимок).`,
    };
  }
  if (codes.has("accelerating_velocity")) {
    return {
      key: "why",
      label: "Почему в отчёте",
      short: "Ускорение",
      detail:
        human[0] ??
        "Серия снимков мониторинга показала рост среднего темпа просмотров до публикации отчёта.",
    };
  }
  if (human.length > 0) {
    return {
      key: "why",
      label: "Почему в отчёте",
      short: `Место №${editionRank}`,
      detail: human[0],
    };
  }
  return {
    key: "why",
    label: "Почему в отчёте",
    short: `Место №${editionRank}`,
    detail:
      "Видео вошло в итоговую daily edition за этот UTC‑день; текстовые причины в payload не сохранены.",
  };
}

export function buildDiWinnerPeriodBlock(
  report: DailyIntelligenceReportSummary | null,
  evidence: Record<string, unknown>,
): WinnerInsightBlock {
  const metrics = formatWinnerMetrics(evidence);
  const windowLine = report ? formatReportAnalyzedPeriod(report) : "—";
  const analyzedAt = report?.source_computed_at
    ? formatDateTimeUtc(report.source_computed_at)
    : null;
  const detailParts = [
    analyzedAt ? `Метрики ниже — на ${analyzedAt} (снимок Attention).` : null,
    `Окно анализа: ${windowLine}.`,
    metrics.ageHours !== "Нет данных"
      ? `Возраст ролика на снимке: ${metrics.ageHours} — это не дата выпуска отчёта.`
      : "Возраст ролика на снимке не сохранён.",
  ].filter(Boolean);

  return {
    key: "period",
    label: "Период данных",
    short: report?.report_date ?? "UTC‑день",
    detail: detailParts.join(" "),
  };
}

export function buildDiWinnerWhatToCheck(params: {
  reportDate: string;
  discoveryProvenanceAvailable: boolean | null;
  hasOutcomeFollowUp: boolean;
}): WinnerInsightBlock {
  if (params.discoveryProvenanceAvailable) {
    return {
      key: "next",
      label: "Что проверить",
      short: "Запросы",
      detail:
        "В «Данные и расчёт» — по каким keyword Radar нашёл видео в этом снимке (не тема ролика).",
    };
  }
  if (params.hasOutcomeFollowUp) {
    return {
      key: "next",
      label: "Что проверить",
      short: "Outcome 72 ч",
      detail:
        "Откройте «Данные и расчёт» — статус контрольного измерения после discovery (может быть «ещё не созрело»).",
    };
  }
  return {
    key: "next",
    label: "Что проверить",
    short: "Сохранить",
    detail: `Сохраните в исследования или откройте на YouTube — архив за ${params.reportDate} не обновляется.`,
  };
}

export function buildDiWinnerInsightBlocks(params: {
  report: DailyIntelligenceReportSummary | null;
  evidence: Record<string, unknown>;
  editionRank: number;
  discoveryProvenanceAvailable: boolean | null;
  hasOutcomeFollowUp: boolean;
}): WinnerInsightBlock[] {
  return [
    buildDiWinnerWhyInReport(params.evidence, params.editionRank),
    buildDiWinnerPeriodBlock(params.report, params.evidence),
    buildDiWinnerWhatToCheck({
      reportDate: params.report?.report_date ?? "—",
      discoveryProvenanceAvailable: params.discoveryProvenanceAvailable,
      hasOutcomeFollowUp: params.hasOutcomeFollowUp,
    }),
  ];
}

export const DI_REASON_MISSING = "Причина в отчёте не сохранена";

export function diWinnerListReasonSummary(
  reasonSummary: string | null | undefined,
): string {
  const trimmed = reasonSummary?.trim();
  return trimmed || DI_REASON_MISSING;
}

export function diWinnerListRankLabel(rank: number): string {
  return `№${rank} в выпуске`;
}
