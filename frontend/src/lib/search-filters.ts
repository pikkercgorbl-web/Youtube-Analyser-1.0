export interface SearchFilters {
  // Video tab.
  hide_shorts: boolean;
  hide_regular: boolean;
  hide_streams: boolean;
  hide_hieroglyphs: boolean;
  virality_only_above_one: boolean;
  virality_min: number | null;
  virality_max: number | null;
  views_min: number | null;
  views_max: number | null;
  // Channel tab.
  subscribers_min: number | null;
  subscribers_max: number | null;
  channel_views_min: number | null;
  channel_views_max: number | null;
  channel_videos_min: number | null;
  channel_videos_max: number | null;
  channel_age_min: number | null;
  channel_age_max: number | null;
}

export const DEFAULT_SEARCH_FILTERS: SearchFilters = {
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
};

/** Strip legacy/unknown keys when loading saved filter presets. */
export function normalizeSearchFilters(value: unknown): SearchFilters {
  const source = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    ...DEFAULT_SEARCH_FILTERS,
    hide_shorts: Boolean(source.hide_shorts),
    hide_regular: Boolean(source.hide_regular),
    hide_streams: Boolean(source.hide_streams),
    hide_hieroglyphs: Boolean(source.hide_hieroglyphs),
    virality_only_above_one: Boolean(source.virality_only_above_one),
    virality_min: parseStoredNumber(source.virality_min),
    virality_max: parseStoredNumber(source.virality_max),
    views_min: parseStoredNumber(source.views_min),
    views_max: parseStoredNumber(source.views_max),
    subscribers_min: parseStoredNumber(source.subscribers_min),
    subscribers_max: parseStoredNumber(source.subscribers_max),
    channel_views_min: parseStoredNumber(source.channel_views_min),
    channel_views_max: parseStoredNumber(source.channel_views_max),
    channel_videos_min: parseStoredNumber(source.channel_videos_min),
    channel_videos_max: parseStoredNumber(source.channel_videos_max),
    channel_age_min: parseStoredNumber(source.channel_age_min),
    channel_age_max: parseStoredNumber(source.channel_age_max),
  };
}

function parseStoredNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export type VideoTypeOption = "all" | "shorts" | "regular";
export type UploadDateOption = "any" | "hour" | "24h" | "week" | "month" | "year";
export type DurationOption = "any" | "short" | "medium" | "long";
export type SortOption = "relevance" | "views" | "rating" | "date";

export interface BaseFilters {
  videoType: VideoTypeOption;
  uploadDate: UploadDateOption;
  duration: DurationOption;
  sortBy: SortOption;
}

export const DEFAULT_BASE_FILTERS: BaseFilters = {
  videoType: "all",
  uploadDate: "any",
  duration: "any",
  sortBy: "relevance",
};

export const VIDEO_TYPE_OPTIONS: { value: VideoTypeOption; label: string }[] = [
  { value: "all", label: "Все видео" },
  { value: "shorts", label: "Искать Shorts" },
  { value: "regular", label: "Искать обычные видео" },
];

export const UPLOAD_DATE_OPTIONS: { value: UploadDateOption; label: string }[] = [
  { value: "any", label: "Любая дата" },
  { value: "hour", label: "За последний час" },
  { value: "24h", label: "За последние 24 часа" },
  { value: "week", label: "За неделю" },
  { value: "month", label: "За месяц" },
  { value: "year", label: "За год" },
];

export const DURATION_OPTIONS: { value: DurationOption; label: string }[] = [
  { value: "any", label: "Любая длительность" },
  { value: "short", label: "Менее 3 минут" },
  { value: "medium", label: "От 3 до 20 минут" },
  { value: "long", label: "Более 20 минут" },
];

export const SORT_OPTIONS: { value: SortOption; label: string }[] = [
  { value: "relevance", label: "По релевантности" },
  { value: "views", label: "По количеству просмотров" },
  { value: "rating", label: "По рейтингу" },
  { value: "date", label: "По дате загрузки" },
];

const SORT_BY_API_MAP: Record<SortOption, string> = {
  relevance: "relevance",
  views: "views",
  rating: "virality",
  date: "date",
};

export interface SearchRequestPayload {
  query: string;
  filters: SearchFilters & {
    published_within: UploadDateOption | null;
    duration: DurationOption | null;
  };
  sort_by: string;
}

export function buildSearchPayload(
  query: string,
  base: BaseFilters,
  advanced: SearchFilters,
): SearchRequestPayload {
  return {
    query,
    filters: {
      ...advanced,
      // Base "video type" select and advanced checkboxes are combined (OR).
      hide_shorts: advanced.hide_shorts || base.videoType === "regular",
      hide_regular: advanced.hide_regular || base.videoType === "shorts",
      hide_streams: advanced.hide_streams || base.videoType === "shorts",
      published_within: base.uploadDate === "any" ? null : base.uploadDate,
      duration: base.duration === "any" ? null : base.duration,
    },
    sort_by: SORT_BY_API_MAP[base.sortBy],
  };
}

export function parseOptionalNumber(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}
