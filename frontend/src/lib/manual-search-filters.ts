/** Manual search filters (UI v2) — local application on loaded YouTube batch. */

import type { SearchRequestPayload } from "./search-filters";

export type ManualSearchPeriod = "all" | "week" | "month" | "year";

export type ManualSearchVideoType = "all" | "regular" | "shorts" | "streams";

export interface ManualSearchFilters {
  publishedPeriod: ManualSearchPeriod;
  durationMinMinutes: number | null;
  durationMaxMinutes: number | null;
  viewsMin: number | null;
  viewsMax: number | null;
  videoType: ManualSearchVideoType;
}

export const DEFAULT_MANUAL_SEARCH_FILTERS: ManualSearchFilters = {
  publishedPeriod: "all",
  durationMinMinutes: null,
  durationMaxMinutes: null,
  viewsMin: null,
  viewsMax: null,
  videoType: "all",
};

export const MANUAL_SEARCH_FILTERS_STORAGE_KEY = "manual_search_filters_v2";

/** Drop legacy persisted shapes (virality, channel tabs, base selects). */
export function loadManualSearchFilters(): ManualSearchFilters {
  if (typeof window === "undefined") {
    return DEFAULT_MANUAL_SEARCH_FILTERS;
  }
  try {
    const raw = window.localStorage.getItem(MANUAL_SEARCH_FILTERS_STORAGE_KEY);
    if (!raw) {
      return DEFAULT_MANUAL_SEARCH_FILTERS;
    }
    const parsed = JSON.parse(raw) as Partial<ManualSearchFilters>;
    return normalizeManualSearchFilters(parsed);
  } catch {
    return DEFAULT_MANUAL_SEARCH_FILTERS;
  }
}

export function persistManualSearchFilters(filters: ManualSearchFilters): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(MANUAL_SEARCH_FILTERS_STORAGE_KEY, JSON.stringify(filters));
}

export function clearLegacyManualSearchStorage(): void {
  if (typeof window === "undefined") {
    return;
  }
  for (const key of [
    "search_filters",
    "video_search_filters",
    "advanced_search_filters",
    "manual_search_base_filters",
  ]) {
    window.localStorage.removeItem(key);
  }
}

export function normalizeManualSearchFilters(value: Partial<ManualSearchFilters>): ManualSearchFilters {
  const period = value.publishedPeriod;
  const videoType = value.videoType;
  return {
    publishedPeriod:
      period === "week" || period === "month" || period === "year" ? period : "all",
    durationMinMinutes: finiteOrNull(value.durationMinMinutes),
    durationMaxMinutes: finiteOrNull(value.durationMaxMinutes),
    viewsMin: finiteOrNull(value.viewsMin),
    viewsMax: finiteOrNull(value.viewsMax),
    videoType:
      videoType === "regular" || videoType === "shorts" || videoType === "streams"
        ? videoType
        : "all",
  };
}

function finiteOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

export function validateManualSearchFilters(filters: ManualSearchFilters): string | null {
  if (filters.durationMinMinutes !== null && filters.durationMaxMinutes !== null) {
    if (filters.durationMinMinutes > filters.durationMaxMinutes) {
      return "Длительность: значение «От» не может быть больше «До».";
    }
  }
  if (filters.viewsMin !== null && filters.viewsMax !== null) {
    if (filters.viewsMin > filters.viewsMax) {
      return "Просмотры: значение «От» не может быть больше «До».";
    }
  }
  return null;
}

/** Active filter groups for badge on «Фильтры» button. */
export function countManualSearchFilterGroups(filters: ManualSearchFilters): number {
  let n = 0;
  if (filters.publishedPeriod !== "all") n += 1;
  if (filters.durationMinMinutes !== null || filters.durationMaxMinutes !== null) n += 1;
  if (filters.viewsMin !== null || filters.viewsMax !== null) n += 1;
  if (filters.videoType !== "all") n += 1;
  return n;
}

export type ManualSearchFilterChip = {
  id: string;
  label: string;
  clear: (filters: ManualSearchFilters) => ManualSearchFilters;
};

export function manualSearchFilterChips(filters: ManualSearchFilters): ManualSearchFilterChip[] {
  const chips: ManualSearchFilterChip[] = [];
  if (filters.publishedPeriod === "week") {
    chips.push({
      id: "period",
      label: "За неделю",
      clear: (f) => ({ ...f, publishedPeriod: "all" }),
    });
  } else if (filters.publishedPeriod === "month") {
    chips.push({
      id: "period",
      label: "За месяц",
      clear: (f) => ({ ...f, publishedPeriod: "all" }),
    });
  } else if (filters.publishedPeriod === "year") {
    chips.push({
      id: "period",
      label: "За год",
      clear: (f) => ({ ...f, publishedPeriod: "all" }),
    });
  }

  if (filters.durationMinMinutes !== null || filters.durationMaxMinutes !== null) {
    const from = filters.durationMinMinutes;
    const to = filters.durationMaxMinutes;
    let label = "Длительность";
    if (from !== null && to !== null) {
      label = `От ${from} до ${to} мин`;
    } else if (from !== null) {
      label = `От ${from} мин`;
    } else if (to !== null) {
      label = `До ${to} мин`;
    }
    chips.push({
      id: "duration",
      label,
      clear: (f) => ({ ...f, durationMinMinutes: null, durationMaxMinutes: null }),
    });
  }

  if (filters.viewsMin !== null || filters.viewsMax !== null) {
    const from = filters.viewsMin;
    const to = filters.viewsMax;
    let label = "Просмотры";
    if (from !== null && to !== null) {
      label = `От ${formatChipNumber(from)} до ${formatChipNumber(to)} просмотров`;
    } else if (from !== null) {
      label = `От ${formatChipNumber(from)} просмотров`;
    } else if (to !== null) {
      label = `До ${formatChipNumber(to)} просмотров`;
    }
    chips.push({
      id: "views",
      label,
      clear: (f) => ({ ...f, viewsMin: null, viewsMax: null }),
    });
  }

  if (filters.videoType === "regular") {
    chips.push({
      id: "type",
      label: "Обычные видео",
      clear: (f) => ({ ...f, videoType: "all" }),
    });
  } else if (filters.videoType === "shorts") {
    chips.push({
      id: "type",
      label: "Shorts",
      clear: (f) => ({ ...f, videoType: "all" }),
    });
  } else if (filters.videoType === "streams") {
    chips.push({
      id: "type",
      label: "Трансляции",
      clear: (f) => ({ ...f, videoType: "all" }),
    });
  }

  return chips;
}

function formatChipNumber(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(value);
}

/** Server payload: no local filters — filtering happens on the loaded batch in the browser. */
export function buildManualSearchApiPayload(query: string): SearchRequestPayload {
  return {
    query,
    sort_by: "relevance",
    filters: {
      hide_shorts: false,
      hide_regular: false,
      hide_streams: false,
      hide_hieroglyphs: false,
      virality_only_above_one: false,
      virality_min: null,
      virality_max: null,
      views_min: null,
      views_max: null,
      subscribers_min: null,
      subscribers_max: null,
      channel_views_min: null,
      channel_views_max: null,
      channel_videos_min: null,
      channel_videos_max: null,
      channel_age_min: null,
      channel_age_max: null,
      published_within: null,
      duration: null,
    },
  };
}
