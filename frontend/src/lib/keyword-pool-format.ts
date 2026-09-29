import { formatDateTimeLocal } from "@/lib/monitoring-format";

import type { TargetKeywordItem } from "./keyword-pool-types";

const MS_HOUR = 3_600_000;
const MS_DAY = 86_400_000;

export function isKeywordDue(row: TargetKeywordItem, now: Date): boolean {
  if (row.lifecycle_status === "archived") {
    return false;
  }
  if (row.next_scan_at == null) {
    return true;
  }
  return new Date(row.next_scan_at).getTime() <= now.getTime();
}

export function isScheduledWithin24h(row: TargetKeywordItem, now: Date): boolean {
  if (row.lifecycle_status === "archived" || !row.next_scan_at) {
    return false;
  }
  const at = new Date(row.next_scan_at).getTime();
  const ref = now.getTime();
  if (Number.isNaN(at)) {
    return false;
  }
  if (at <= ref) {
    return false;
  }
  return at - ref <= 24 * MS_HOUR;
}

export function matchesUnscheduledOrArchived(row: TargetKeywordItem): boolean {
  if (row.lifecycle_status === "archived") {
    return true;
  }
  return row.lifecycle_status !== "archived" && row.next_scan_at == null;
}

export function formatScanIntervalSeconds(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) {
    return "—";
  }
  if (seconds % 3600 === 0) {
    const hours = seconds / 3600;
    return `${hours} ч`;
  }
  if (seconds % 60 === 0) {
    const minutes = seconds / 60;
    return `${minutes} мин`;
  }
  return `${seconds} с`;
}

export type NextScanPresentation = {
  text: string;
  title: string;
};

export function formatNextScanPresentation(
  row: TargetKeywordItem,
  now: Date,
): NextScanPresentation {
  if (row.lifecycle_status === "archived") {
    return { text: "Не сканируется", title: "Архивный ключ не участвует в плановом сканировании." };
  }
  if (row.next_scan_at == null) {
    return {
      text: "Пора сканировать",
      title: "Следующий скан ещё не запланирован — ключ считается готовым к сканированию.",
    };
  }
  const atMs = new Date(row.next_scan_at).getTime();
  const refMs = now.getTime();
  const title = formatDateTimeLocal(row.next_scan_at);
  if (Number.isNaN(atMs)) {
    return { text: "Пора сканировать", title };
  }
  if (atMs <= refMs) {
    return { text: "Пора сканировать", title };
  }
  const diffMs = atMs - refMs;
  const hours = Math.ceil(diffMs / MS_HOUR);
  if (hours < 24) {
    return { text: `Через ${hours} ч`, title };
  }
  const nowLocal = new Date(now);
  const tomorrow = new Date(nowLocal);
  tomorrow.setDate(tomorrow.getDate() + 1);
  const scanDate = new Date(row.next_scan_at);
  if (
    scanDate.getFullYear() === tomorrow.getFullYear() &&
    scanDate.getMonth() === tomorrow.getMonth() &&
    scanDate.getDate() === tomorrow.getDate()
  ) {
    return { text: "Завтра", title };
  }
  const days = Math.ceil(diffMs / MS_DAY);
  if (days <= 7) {
    return { text: `Через ${days} д`, title };
  }
  return { text: formatDateTimeLocal(row.next_scan_at), title };
}

export function formatLastScan(iso: string | null | undefined): { text: string; title: string } {
  const title = formatDateTimeLocal(iso);
  if (!iso) {
    return { text: "Ещё не сканировался", title: "—" };
  }
  return { text: formatDateTimeLocal(iso), title };
}
