import type { TargetKeywordItem, PoolMetrics } from "./keyword-pool-types";
import { isKeywordDue, isScheduledWithin24h } from "./keyword-pool-format";

export function computePoolMetrics(rows: TargetKeywordItem[], now: Date): PoolMetrics {
  let probation = 0;
  let active = 0;
  let weak = 0;
  let archived = 0;
  let dueNow = 0;
  let scheduledNext24h = 0;

  for (const row of rows) {
    switch (row.lifecycle_status) {
      case "probation":
        probation += 1;
        break;
      case "active":
        active += 1;
        break;
      case "weak":
        weak += 1;
        break;
      case "archived":
        archived += 1;
        break;
      default:
        break;
    }
    if (isKeywordDue(row, now)) {
      dueNow += 1;
    }
    if (isScheduledWithin24h(row, now)) {
      scheduledNext24h += 1;
    }
  }

  const total = rows.length;
  const working = total - archived;

  return {
    total,
    working,
    probation,
    active,
    weak,
    archived,
    dueNow,
    scheduledNext24h,
  };
}

export type SummaryLine = { text: string; emphasis?: boolean };

export function poolSummaryLines(metrics: PoolMetrics): SummaryLine[] {
  const lines: SummaryLine[] = [];

  if (metrics.total === 0) {
    lines.push({ text: "Пул ключей пуст.", emphasis: true });
    return lines;
  }

  lines.push({
    text: `${metrics.working.toLocaleString("ru-RU")} ключей в рабочем пуле.`,
    emphasis: true,
  });

  if (metrics.dueNow > 0) {
    lines.push({
      text: `${metrics.dueNow.toLocaleString("ru-RU")} уже пора просканировать.`,
      emphasis: true,
    });
  } else {
    lines.push({ text: "Очередь сканирования сейчас пуста." });
  }

  if (metrics.probation > 0) {
    lines.push({
      text: `${metrics.probation.toLocaleString("ru-RU")} новых ключей на пробном этапе.`,
    });
  }

  return lines;
}

export function poolDueEmptyNote(metrics: PoolMetrics): string | null {
  if (metrics.total === 0) {
    return null;
  }
  if (metrics.dueNow === 0) {
    return "Сейчас нет ключей, которым пора сканироваться.";
  }
  return null;
}
