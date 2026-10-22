import type { KeywordPoolSummary } from "@/lib/keyword-pool-types";

export function keywordPoolQueueContextLines(
  summary: KeywordPoolSummary,
  clientDueNow: number,
): { text: string; emphasis?: boolean }[] {
  const lines: { text: string; emphasis?: boolean }[] = [
    {
      text: `За последние 24 ч Discovery обработал ${summary.unique_keywords_scanned_last_24h.toLocaleString("ru-RU")} уникальных ключей (${summary.keyword_scan_runs_last_24h.toLocaleString("ru-RU")} scan-run).`,
    },
    {
      text:
        "«Пора просканировать» значит, что ключ ждёт планового прохода по расписанию (next_scan_at), а не то, что worker остановился.",
      emphasis: true,
    },
  ];
  if (clientDueNow > summary.unique_keywords_scanned_last_24h) {
    lines.push({
      text:
        "Очередь due может быть больше суточной пропускной способности — это ограничение batch/интервала, не признак «здоровья» только по статусу worker.",
    });
  }
  lines.push({
    text: `Интервалы policy: probation ${summary.probation_interval_hours} ч, active ${summary.active_interval_hours} ч, weak ${summary.weak_interval_hours} ч.`,
  });
  return lines;
}
