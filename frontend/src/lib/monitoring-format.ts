import { formatCompactNumber, formatNumber } from "@/lib/utils";

import type { MonitoringWorkerState } from "./monitoring-types";

export function formatMonitoringVph(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  if (value >= 1000) {
    return formatCompactNumber(value);
  }
  return formatNumber(Math.round(value * 10) / 10);
}

export function formatMonitoringViews(value: number | null | undefined): string {
  if (value == null) {
    return "—";
  }
  return formatCompactNumber(value);
}

export function formatAgeHours(hours: number | null | undefined): string {
  if (hours == null || Number.isNaN(hours)) {
    return "—";
  }
  if (hours < 48) {
    return `${(Math.round(hours * 10) / 10).toLocaleString("ru-RU")} ч`;
  }
  const days = Math.floor(hours / 24);
  const rem = Math.round(hours % 24);
  if (rem === 0) {
    return `${days} д`;
  }
  return `${days} д ${rem} ч`;
}

/** Relative snapshot age for display only (no quality thresholds). */
export function formatSnapshotRelative(
  iso: string | null | undefined,
  referenceMs: number = Date.now(),
): string {
  if (!iso) {
    return "снимок отсутствует";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  const diffMs = referenceMs - date.getTime();
  if (diffMs < 0) {
    return formatDateTimeLocal(iso);
  }
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) {
    return "обновлено только что";
  }
  if (minutes < 60) {
    return `обновлено ${minutes} мин назад`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 48) {
    return `обновлено ${hours} ч назад`;
  }
  const days = Math.floor(hours / 24);
  return `обновлено ${days} д назад`;
}

export function formatDateTimeLocal(iso: string | null | undefined): string {
  if (!iso) {
    return "—";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function shortenRunId(runId: string): string {
  if (runId.length <= 28) {
    return runId;
  }
  return `${runId.slice(0, 22)}…`;
}

export function workerStatusLabel(status: MonitoringWorkerState): string {
  switch (status) {
    case "running":
      return "Недавняя активность циклов";
    case "stale":
      return "Давно не было активности циклов";
    case "stopped":
      return "Воркер остановлен";
    default:
      return "Статус недоступен";
  }
}

export function workerStatusHint(status: MonitoringWorkerState): string {
  switch (status) {
    case "running":
      return "Недавно завершался цикл мониторинга или обновлялся heartbeat воркера.";
    case "stale":
      return "Долго нет завершённых циклов и heartbeat. Возможен зависший процесс (возраст lock — отдельная диагностика).";
    case "stopped":
      return "В БД выставлен флаг остановки мониторингового воркера.";
    default:
      return "Нет активной lock-записи. Обычно воркер не запущен.";
  }
}
