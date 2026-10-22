import type { DailyIntelligenceReportStatus } from "./daily-intelligence-types";

export const DAILY_INTELLIGENCE_STATUS_LABELS: Record<
  DailyIntelligenceReportStatus,
  string
> = {
  provisional: "Предварительный",
  complete: "Зафиксирован",
  partial: "Зафиксирован с ограничениями",
  unavailable: "Нет публикаций",
};

export const DAILY_INTELLIGENCE_STATUS_HINTS: Record<
  DailyIntelligenceReportStatus,
  string
> = {
  provisional:
    "UTC-день ещё не закрыт; финальная редакция может измениться при следующей публикации Attention.",
  complete: "День закрыт; данные заморожены на последней публикации Attention за этот UTC-день.",
  partial:
    "День закрыт, но есть ограничения покрытия (например, последняя публикация далеко от конца UTC-дня).",
  unavailable: "За этот UTC-день не было успешной публикации Attention.",
};

export function dailyIntelligenceStatusLabel(status: string): string {
  if (status in DAILY_INTELLIGENCE_STATUS_LABELS) {
    return DAILY_INTELLIGENCE_STATUS_LABELS[status as DailyIntelligenceReportStatus];
  }
  return status;
}

export function dailyIntelligenceStatusHint(status: string): string | null {
  if (status in DAILY_INTELLIGENCE_STATUS_HINTS) {
    return DAILY_INTELLIGENCE_STATUS_HINTS[status as DailyIntelligenceReportStatus];
  }
  return null;
}
