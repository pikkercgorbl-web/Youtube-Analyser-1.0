import type { SummaryLine, SummaryTone } from "@/components/design-system/summary-strip";
import type { MonitoringOverview, MonitoringWorkerStatus } from "@/lib/monitoring-types";

import { formatCount } from "@/lib/operations-format";

export type MonitoringSummary = {
  tone: SummaryTone;
  lines: SummaryLine[];
};

export function priorityMonitoringSummary(
  overview: MonitoringOverview | null,
  options?: { loading?: boolean },
): MonitoringSummary {
  if (!overview) {
    return {
      tone: "neutral",
      lines: [
        {
          text: options?.loading ? "Загрузка сводки очереди…" : "Сводка очереди недоступна.",
          emphasis: true,
        },
      ],
    };
  }

  const lines: SummaryLine[] = [];
  let tone: SummaryTone = "informational";

  if (overview.overdue_count > 0) {
    lines.push({
      text: `${formatCount(overview.overdue_count)} видео просрочены по плану мониторинга.`,
      emphasis: true,
    });
    tone = "warning";
  }

  if (overview.due_count > 0) {
    lines.push({
      text: `${formatCount(overview.due_count)} видео готовы к следующему снимку.`,
      emphasis: lines.length === 0,
    });
    if (tone === "informational") {
      tone = "warning";
    }
  }

  if (lines.length === 0) {
    if (overview.active_monitored_count === 0) {
      return {
        tone: "neutral",
        lines: [
          {
            text: "Monitoring работает, но свежих подходящих видео нет.",
            emphasis: true,
          },
        ],
      };
    }
    return {
      tone: "informational",
      lines: [{ text: "Сейчас нет видео, требующих обработки.", emphasis: true }],
    };
  }

  return { tone, lines };
}

export function breakoutMonitoringSummary(
  rankedTotal: number,
  activeMonitoredCount: number,
): MonitoringSummary {
  if (rankedTotal > 0) {
    return {
      tone: "informational",
      lines: [
        {
          text: `${formatCount(rankedTotal)} видео в текущем breakout v1 рейтинге.`,
          emphasis: true,
        },
        {
          text: "Рейтинг основан прежде всего на текущем VPH и показывает относительную силу среди подходящих для анализа.",
        },
      ],
    };
  }

  if (activeMonitoredCount > 0) {
    return {
      tone: "neutral",
      lines: [
        {
          text: "Видео в базе есть, но они не подходят под текущие правила breakout-анализа.",
          emphasis: true,
        },
      ],
    };
  }

  return {
    tone: "neutral",
    lines: [{ text: "Сейчас нет видео, подходящих для breakout-рейтинга.", emphasis: true }],
  };
}

export function monitoringWorkerSummaryLine(worker: MonitoringWorkerStatus | null): string | null {
  if (!worker) {
    return null;
  }
  if (worker.status === "running") {
    return "Lock воркера активен.";
  }
  if (worker.status === "stale") {
    return "Сигнал воркера устарел — проверьте процесс мониторинга.";
  }
  return null;
}

export const MONITORING_MODE_PRIORITY_HELP =
  "Очередь обработки: due, overdue и следующие контрольные точки для снимков метрик.";

export const MONITORING_MODE_BREAKOUT_HELP =
  "Breakout v1 ранжирует подходящие видео по текущему VPH. Просмотры используются как tie-break. Рейтинг не зависит от Tier и лимитов capture pool.";

export const TIER_OPERATIONAL_HELP =
  "Tier определяет частоту и бюджет наблюдения. Он не является оценкой качества видео.";

export const CAPTURE_POOL_HELP =
  "Пул определяет, какие видео получают ресурсы мониторинга сейчас. Он не является рейтингом качества.";

export const CHECKPOINT_HELP =
  "Контрольная точка — запланированный момент, когда система должна снять новое состояние видео.";
