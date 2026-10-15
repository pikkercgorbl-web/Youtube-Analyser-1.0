import type { EnrichedVideoModel } from "@/lib/types";

import type { ManualSearchFilters, ManualSearchPeriod } from "./manual-search-filters";
import { isStreamPublishedText, parseDurationSeconds } from "./manual-search-published-format";

const PERIOD_MAX_DAYS: Record<Exclude<ManualSearchPeriod, "all">, number> = {
  week: 7,
  month: 30,
  year: 365,
};

function parseRelativeDays(publishedText: string): number {
  const normalized = publishedText
    .replace(/\u00a0/g, " ")
    .replace(/\u202f/g, " ")
    .trim()
    .toLowerCase();
  if (!normalized) return -1;
  if (["just now", "moments ago", "только что", "сейчас"].includes(normalized)) return 0;

  const patterns: Array<[RegExp, number]> = [
    [/(\d+)\s*(?:years?|год(?:а|у)?|лет)\b/i, 365],
    [/(\d+)\s*(?:months?|месяц(?:а|ев)?)\b/i, 30],
    [/(\d+)\s*(?:weeks?|недел(?:я|и|ь|ю|ей)?|недель)\b/i, 7],
    [/(\d+)\s*(?:days?|день|дня|дней)\b/i, 1],
    [/(\d+)\s*(?:hours?|час(?:а|ов)?)\b/i, 0],
    [/(\d+)\s*(?:minutes?|минут(?:а|ы|у)?)\b/i, 0],
  ];
  for (const [re, mult] of patterns) {
    const m = normalized.match(re);
    if (m) return parseInt(m[1], 10) * mult;
  }
  return -1;
}

export type ManualSearchVideoKind = "short" | "regular" | "stream" | "unknown";

export function classifyManualSearchVideo(item: EnrichedVideoModel): ManualSearchVideoKind {
  if (item.video.is_short) return "short";
  if (isStreamPublishedText(item.video.published_text, item.video.title)) return "stream";
  const title = (item.video.title ?? "").toLowerCase();
  if (title.includes("#shorts") || title.includes("#short")) return "short";
  const duration = parseDurationSeconds(item.video.duration_text);
  if (duration > 0 || (item.video.duration_text ?? "").trim()) return "regular";
  return "unknown";
}

function inRange(value: number, min: number | null, max: number | null): boolean {
  if (min !== null && value < min) return false;
  if (max !== null && value > max) return false;
  return true;
}

export function applyManualSearchLocalFilters(
  items: EnrichedVideoModel[],
  filters: ManualSearchFilters,
): EnrichedVideoModel[] {
  return items.filter((item) => {
    if (filters.publishedPeriod !== "all") {
      const text = (item.video.published_text ?? "").trim();
      if (!text) return false;
      const days = parseRelativeDays(text);
      if (days < 0) return false;
      if (days > PERIOD_MAX_DAYS[filters.publishedPeriod]) return false;
    }

    const durationSec = parseDurationSeconds(item.video.duration_text);
    if (filters.durationMinMinutes !== null || filters.durationMaxMinutes !== null) {
      if (durationSec <= 0) return false;
      const minSec = (filters.durationMinMinutes ?? 0) * 60;
      const maxSec =
        filters.durationMaxMinutes !== null ? filters.durationMaxMinutes * 60 : Number.POSITIVE_INFINITY;
      if (durationSec < minSec || durationSec > maxSec) return false;
    }

    const views = item.video.views_count;
    if (filters.viewsMin !== null || filters.viewsMax !== null) {
      if (views == null || views <= 0) return false;
      if (!inRange(views, filters.viewsMin, filters.viewsMax)) return false;
    }

    if (filters.videoType !== "all") {
      const kind = classifyManualSearchVideo(item);
      if (filters.videoType === "shorts") {
        if (kind !== "short") return false;
      } else if (filters.videoType === "streams") {
        if (kind !== "stream") return false;
      } else if (filters.videoType === "regular") {
        if (kind !== "regular") return false;
      }
    }

    return true;
  });
}

export function mergeEnrichedPreservingOrder(
  base: EnrichedVideoModel[],
  enriched: EnrichedVideoModel[],
): EnrichedVideoModel[] {
  const byId = new Map(enriched.map((row) => [row.video.video_id, row]));
  return base.map((row) => byId.get(row.video.video_id) ?? row);
}
