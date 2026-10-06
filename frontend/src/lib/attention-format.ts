import { formatAgeHours, formatDateTimeLocal, formatMonitoringViews, formatMonitoringVph } from "@/lib/monitoring-format";
import { formatCompactNumber, youtubeThumbnail, youtubeVideoUrl } from "@/lib/utils";

import type { AttentionPattern, AttentionVideoWinner } from "./attention-types";

export { youtubeThumbnail, youtubeVideoUrl };

const BREAKOUT_WINNER_RE = /breakout\s+winner/i;

export function rewriteHumanReason(text: string): string {
  let out = text.replace(
    /(\d+)\s+breakout-eligible videos/gi,
    "$1 видео подходят для анализа Breakout",
  );
  out = out.replace(/breakout-eligible/gi, "подходят для анализа Breakout");
  out = out.replace(/qualify for Breakout analysis/gi, "подходят для анализа Breakout");
  out = out.replace(/^Context:/gi, "Контекст:");
  return out;
}

export function humanReasonsForDisplay(reasons: string[] | undefined): string[] {
  return (reasons ?? []).map(rewriteHumanReason);
}

export function claimsBreakoutWinner(text: string): boolean {
  return BREAKOUT_WINNER_RE.test(text);
}

export function groupingSourceLabel(kind: string): string {
  switch (kind) {
    case "title_phrase":
      return "Источник группировки: повторяющаяся фраза в названии";
    case "keyword_provenance":
      return "Источник группировки: общий поисковый keyword";
    case "video_topic":
      return "Источник группировки: общий topic";
    default:
      return `Источник группировки: ${kind}`;
  }
}

export function groupingSourceShort(kind: string): string {
  switch (kind) {
    case "title_phrase":
      return "фраза в названии";
    case "keyword_provenance":
      return "поисковый keyword";
    case "video_topic":
      return "video topic";
    default:
      return kind;
  }
}

export function formatOptionalCount(value: number | null | undefined): string | null {
  if (value == null || Number.isNaN(value)) {
    return null;
  }
  return formatCompactNumber(value);
}

export function formatOptionalViews(value: number | null | undefined): string | null {
  if (value == null) {
    return null;
  }
  return formatMonitoringViews(value);
}

export function formatOptionalVph(value: number | null | undefined): string | null {
  if (value == null || Number.isNaN(value)) {
    return null;
  }
  return `${formatMonitoringVph(value)} VPH`;
}

export function formatOptionalSubscribers(value: number | null | undefined): string | null {
  if (value == null || Number.isNaN(value) || value <= 0) {
    return null;
  }
  return formatCompactNumber(value);
}

export function formatOptionalAge(hours: number | null | undefined): string | null {
  if (hours == null || Number.isNaN(hours)) {
    return null;
  }
  return formatAgeHours(hours);
}

export function snapshotFreshnessLabel(
  computedAt: string | null | undefined,
  nowMs: number = Date.now(),
): string {
  if (!computedAt) {
    return "снимок отсутствует";
  }
  const date = new Date(computedAt);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  const diffMs = nowMs - date.getTime();
  if (diffMs < 0) {
    return `снимок ${formatDateTimeLocal(computedAt)}`;
  }
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) {
    return "Обновлено только что";
  }
  if (minutes < 60) {
    return `Обновлено ${minutes} мин назад`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 48) {
    return `Обновлено ${hours} ч назад`;
  }
  const days = Math.floor(hours / 24);
  return `Обновлено ${days} д назад`;
}

export function windowHoursLabel(hours: number | null | undefined): string {
  if (hours == null) {
    return "окно неизвестно";
  }
  if (hours === 24) {
    return "Окно: последние 24 часа";
  }
  return `Окно: последние ${hours} ч`;
}

export function candidateCountLabel(count: number | null | undefined): string {
  if (count == null) {
    return "Проанализировано: —";
  }
  return `Проанализировано: ${count.toLocaleString("ru-RU")} видео`;
}

export type PatternActivity = {
  available: boolean;
  previous48: number;
  previous24: number;
  last24: number;
  label: string;
};

export function patternActivity(pattern: Pick<
  AttentionPattern,
  "videos_previous_48_24h" | "videos_previous_24h" | "videos_last_24h" | "first_seen_at" | "latest_seen_at"
>): PatternActivity {
  const previous48 = pattern.videos_previous_48_24h ?? 0;
  const previous24 = pattern.videos_previous_24h ?? 0;
  const last24 = pattern.videos_last_24h ?? 0;
  const hasAny = previous48 > 0 || previous24 > 0 || last24 > 0 || Boolean(pattern.first_seen_at || pattern.latest_seen_at);
  if (!hasAny) {
    return { available: false, previous48, previous24, last24, label: "Недостаточно истории" };
  }
  return {
    available: true,
    previous48,
    previous24,
    last24,
    label: `${previous48} → ${previous24} → ${last24}`,
  };
}

export function confirmed72hCount(videos: Pick<AttentionVideoWinner, "delayed_outcome_state">[]): number {
  return videos.filter((row) => row.delayed_outcome_state === "confirmed").length;
}

export function winnerSignalFlags(row: {
  reason_codes?: string[];
  acceleration_state?: string | null;
  delayed_outcome_state?: string | null;
  channel_relative_signal?: { status: string } | null;
  in_winner_snapshot?: boolean;
}): {
  winner: boolean;
  accelerating: boolean;
  confirmed72h: boolean;
  smallChannel: boolean;
  strongerThanChannel: boolean;
} {
  const codes = new Set(row.reason_codes ?? []);
  return {
    winner: Boolean(row.in_winner_snapshot) || codes.has("breakout_high_rank"),
    accelerating: row.acceleration_state === "accelerating",
    confirmed72h: row.delayed_outcome_state === "confirmed" || codes.has("confirmed_72h_growth"),
    smallChannel: codes.has("small_channel_in_observed_universe"),
    strongerThanChannel: codes.has("channel_relative_outlier") || row.channel_relative_signal?.status === "production_ready",
  };
}

export function canonicalYoutubeUrl(videoId: string, stored?: string | null): string {
  if (stored && stored.startsWith("https://www.youtube.com/watch?v=")) {
    return stored;
  }
  return youtubeVideoUrl(videoId);
}

export function patternDetailHref(patternKey: string): string {
  return `/opportunities/patterns/${encodeURIComponent(patternKey)}`;
}

export function familyDetailHref(familyKey: string): string {
  return `/opportunities/families/${encodeURIComponent(familyKey)}`;
}
