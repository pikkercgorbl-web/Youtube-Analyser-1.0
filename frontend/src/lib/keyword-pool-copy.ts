import type { LifecycleStatus } from "@/lib/design-system/labels";

import type { TargetKeywordSourceType } from "./keyword-pool-types";

export const POOL_LIFECYCLE_HELP =
  "Lifecycle определяет частоту и режим сканирования keyword. Это не оценка качества.";

export const ARCHIVED_POOL_HELP =
  "Архивные ключи сохраняются в истории и не участвуют в плановом сканировании.";

export const SCAN_INTERVAL_TOOLTIP =
  "Интервал определяет, как часто keyword планируется для повторного сканирования.";

export const CLIENT_FILTER_NOTE =
  "Фильтры и сортировка выполняются на клиенте для текущего списка ключей (ограничение этапа 1.21F).";

/** Scheduling-focused lifecycle labels on the pool page (weak ≠ «плохой ключ»). */
export function poolLifecycleLabel(status: LifecycleStatus | string | null | undefined): string {
  if (!status) {
    return "—";
  }
  switch (String(status).toLowerCase()) {
    case "probation":
      return "Пробный";
    case "active":
      return "Активный";
    case "weak":
      return "Редкий";
    case "archived":
      return "Архив";
    default:
      return String(status);
  }
}

const SOURCE_LABELS: Record<string, string> = {
  seed: "Исходный",
  suggestion: "Подсказка",
  related: "Связанный",
  channel: "Из канала",
  manual: "Добавлен вручную",
  llm: "LLM",
};

export function poolSourceLabel(source: TargetKeywordSourceType | null | undefined): string {
  if (!source) {
    return "—";
  }
  const key = String(source).toLowerCase();
  return SOURCE_LABELS[key] ?? source;
}

const REASON_LABELS: Record<string, string> = {
  created: "Создан",
  "manual review": "Ручная проверка",
};

export function poolStatusReasonLabel(reason: string | null | undefined): string {
  if (!reason?.trim()) {
    return "—";
  }
  const trimmed = reason.trim();
  const mapped = REASON_LABELS[trimmed.toLowerCase()];
  if (mapped) {
    return mapped;
  }
  if (trimmed.toLowerCase().startsWith("discovered via")) {
    return trimmed;
  }
  return trimmed;
}
