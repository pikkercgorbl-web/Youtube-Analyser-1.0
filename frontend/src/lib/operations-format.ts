import { formatDateTimeLocal, shortenRunId } from "@/lib/monitoring-format";

import type { ActivityState } from "./operations-types";

export { formatDateTimeLocal, shortenRunId };

/** Parse API timestamps; naive strings are treated as UTC (legacy rows). */
export function parseApiInstant(iso: string): number {
  const trimmed = iso.trim();
  if (/[Zz]|[+-]\d{2}:\d{2}$/.test(trimmed)) {
    return new Date(trimmed).getTime();
  }
  const normalized = trimmed.includes("T") ? trimmed : trimmed.replace(" ", "T");
  return new Date(`${normalized}Z`).getTime();
}

/** Relative time from API reference clock (generated_at), not client wall clock. */
export function formatRelativeTime(
  iso: string | null | undefined,
  referenceIso: string | null | undefined,
): { relative: string; title: string } {
  const title = formatDateTimeLocal(iso);
  if (!iso || !referenceIso) {
    return { relative: "—", title };
  }
  const at = parseApiInstant(iso);
  const ref = parseApiInstant(referenceIso);
  if (Number.isNaN(at) || Number.isNaN(ref)) {
    return { relative: "—", title };
  }
  const diffMs = ref - at;
  if (diffMs < 0) {
    return { relative: formatDateTimeLocal(iso), title };
  }
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) {
    return { relative: "только что", title };
  }
  if (minutes < 60) {
    return { relative: `${minutes} мин назад`, title };
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 48) {
    return { relative: `${hours} ч назад`, title };
  }
  const days = Math.floor(hours / 24);
  return { relative: `${days} д назад`, title };
}

export function activityStateLabel(state: ActivityState): string {
  switch (state) {
    case "active_recently":
      return "Недавняя активность";
    case "stale_activity":
      return "Устаревшая активность";
    case "error":
      return "Ошибка";
    default:
      return "Неизвестно";
  }
}

export function activityStateHint(state: ActivityState): string {
  switch (state) {
    case "active_recently":
      return "По данным последнего цикла или lock-записи.";
    case "stale_activity":
      return "Давно не было успешного цикла или lock устарел.";
    case "error":
      return "Последний цикл завершился с ошибкой или есть сообщение об ошибке.";
    default:
      return "Недостаточно сигналов для оценки активности.";
  }
}

export function formatRuntimeSeconds(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) {
    return "—";
  }
  if (seconds < 60) {
    return `${Math.round(seconds * 10) / 10} с`;
  }
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return s > 0 ? `${m} мин ${s} с` : `${m} мин`;
}

export function formatCount(value: number): string {
  return value.toLocaleString("ru-RU");
}
