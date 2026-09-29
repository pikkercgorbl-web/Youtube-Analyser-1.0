import type { SummaryLine, SummaryTone } from "@/components/design-system/summary-strip";
import type {
  DiscoveryOperationsBlock,
  KeywordOutcomeOperationsBlock,
  MonitoringOperationsBlock,
  OperationsErrorsBlock,
  SnapshotOperationsBlock,
} from "@/lib/operations-types";

import { formatCount } from "./operations-format";

export type OperationsSummary = {
  tone: SummaryTone;
  lines: SummaryLine[];
};

function discoveryCycleFailed(discovery: DiscoveryOperationsBlock): boolean {
  const status = (discovery.last_cycle_status ?? "").toLowerCase();
  return (
    discovery.worker.activity_state === "error" ||
    Boolean(discovery.last_error) ||
    status === "failed" ||
    status === "error"
  );
}

export function discoveryOperationsSummary(
  discovery: DiscoveryOperationsBlock,
  lastCycleRelative: string,
): OperationsSummary {
  if (discoveryCycleFailed(discovery)) {
    return {
      tone: "error",
      lines: [{ text: "Discovery завершился с ошибкой.", emphasis: true }],
    };
  }

  if (discovery.worker.activity_state === "stale_activity") {
    const lines: SummaryLine[] = [
      { text: "Discovery давно не запускался.", emphasis: true },
    ];
    if (discovery.keywords_due_now > 0) {
      lines.push({
        text: `${formatCount(discovery.keywords_due_now)} ключей ждут сканирования.`,
      });
    }
    return { tone: "warning", lines };
  }

  if (discovery.last_cycle_finished_at) {
    const lines: SummaryLine[] = [
      {
        text: `Discovery работает. Последний цикл завершён ${lastCycleRelative}.`,
        emphasis: true,
      },
    ];
    if (discovery.keyword_errors_last_cycle > 0) {
      lines.push({
        text: `В последнем цикле ошибок по ключам: ${formatCount(discovery.keyword_errors_last_cycle)}.`,
      });
      return { tone: "warning", lines };
    }
    return { tone: "informational", lines };
  }

  return {
    tone: "neutral",
    lines: [{ text: "Записанных циклов discovery пока нет.", emphasis: true }],
  };
}

export function monitoringOperationsSummary(
  monitoring: MonitoringOperationsBlock,
  snapshotsLast24h: number,
): OperationsSummary {
  const status = (monitoring.last_cycle_status ?? "").toLowerCase();
  if (monitoring.worker.activity_state === "error" || status === "failed") {
    return {
      tone: "error",
      lines: [{ text: "Последний цикл monitoring завершился с ошибкой.", emphasis: true }],
    };
  }

  if (monitoring.loaded_video_count > 0 && monitoring.eligible_video_count === 0) {
    return {
      tone: "warning",
      lines: [
        {
          text: "Видео в базе есть, но сейчас нет видео, подходящих под текущие правила мониторинга.",
          emphasis: true,
        },
      ],
    };
  }

  if (monitoring.worker.activity_state === "stale_activity") {
    const staleLine =
      snapshotsLast24h === 0
        ? "Monitoring давно не создавал новых снимков."
        : "Monitoring давно не выполнял успешных циклов.";
    return {
      tone: "warning",
      lines: [{ text: staleLine, emphasis: true }],
    };
  }

  if (monitoring.inserted_snapshot_count > 0) {
    return {
      tone: "informational",
      lines: [
        {
          text: "Monitoring работает и сохраняет новые снимки.",
          emphasis: true,
        },
      ],
    };
  }

  if (monitoring.eligible_video_count === 0) {
    return {
      tone: "neutral",
      lines: [
        {
          text: "Monitoring запускается, но сейчас нет видео, подходящих для наблюдения.",
          emphasis: true,
        },
      ],
    };
  }

  return {
    tone: "neutral",
    lines: [{ text: "Monitoring активен; в последнем цикле новых снимков не сохранено.", emphasis: true }],
  };
}

export function snapshotOperationsSummary(snapshots: SnapshotOperationsBlock): OperationsSummary {
  if (snapshots.snapshots_last_24h === 0) {
    return {
      tone: "neutral",
      lines: [{ text: "Новых снимков за последние 24 ч нет.", emphasis: true }],
    };
  }
  return {
    tone: "informational",
    lines: [
      {
        text: `За последние 24 ч сохранено ${formatCount(snapshots.snapshots_last_24h)} снимков.`,
        emphasis: true,
      },
    ],
  };
}

export function outcome72hOperationsSummary(outcomes: KeywordOutcomeOperationsBlock): OperationsSummary {
  const lines: SummaryLine[] = [];

  if (outcomes.valid_72h_outcome_count === 0) {
    lines.push({ text: "Пока нет валидных 72 ч исходов.", emphasis: true });
  } else {
    lines.push({
      text: `Зафиксировано ${formatCount(outcomes.valid_72h_outcome_count)} валидных 72 ч исхода.`,
      emphasis: true,
    });
  }

  if (outcomes.matures_next_24h > 0) {
    lines.push({
      text: `${formatCount(outcomes.matures_next_24h)} наблюдений дозреют в ближайшие 24 ч.`,
    });
  }

  if (
    outcomes.matured_72h_count > 0 &&
    outcomes.missing_72h_outcome_count > 0 &&
    outcomes.valid_72h_outcome_count === 0
  ) {
    lines.push({
      text: `${formatCount(outcomes.missing_72h_outcome_count)} наблюдений уже созрели, но подходящего снимка на горизонте 72 ч нет — это не сбой пайплайна.`,
    });
  }

  return {
    tone: outcomes.valid_72h_outcome_count > 0 ? "informational" : "neutral",
    lines,
  };
}

export function operationsBlockedSummary(
  discovery: DiscoveryOperationsBlock,
  monitoring: MonitoringOperationsBlock,
  errors: OperationsErrorsBlock,
): OperationsSummary | null {
  const hasErrors =
    Boolean(errors.discovery_last_cycle_error) || errors.monitoring_recent_error_summaries.length > 0;
  const staleDiscovery = discovery.worker.activity_state === "stale_activity";
  const staleMonitoring = monitoring.worker.activity_state === "stale_activity";

  if (!hasErrors && !staleDiscovery && !staleMonitoring) {
    return null;
  }

  const lines: SummaryLine[] = [];
  if (hasErrors) {
    lines.push({ text: "Есть ошибки в последних циклах — см. блок «Ошибки» ниже.", emphasis: true });
  }
  if (staleDiscovery && staleMonitoring) {
    lines.push({ text: "Discovery и monitoring давно не показывали свежую активность." });
  } else if (staleDiscovery) {
    lines.push({ text: "Discovery давно не показывал свежую активность." });
  } else if (staleMonitoring) {
    lines.push({ text: "Monitoring давно не показывал свежую активность." });
  }

  return {
    tone: hasErrors ? "error" : "warning",
    lines,
  };
}

export const OUTCOME_72H_HELP =
  "72 ч исход появляется, когда после находки видео проходит около 72 часов и у системы есть подходящий снимок рядом с этой точкой.";

export const LIVENESS_DISCLAIMER =
  "Статус активности выводится из последнего цикла и lock-записей; настоящий heartbeat процесса может отличаться.";
