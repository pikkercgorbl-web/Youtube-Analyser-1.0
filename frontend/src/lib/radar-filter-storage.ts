import type { ExplosiveChannelSortOption, RadarUploadPeriod } from "./types";

export const RADAR_FILTER_STORAGE_KEYS = {
  minViews: "radar_min_views",
  minViralCoeff: "radar_min_viral_coeff",
  uploadPeriod: "radar_upload_period",
  sortBy: "radar_sort_by",
} as const;

const VALID_UPLOAD_PERIODS: RadarUploadPeriod[] = [
  "all",
  "month",
  "3_months",
  "6_months",
  "year",
];

const VALID_SORT_OPTIONS: ExplosiveChannelSortOption[] = [
  "viral_coefficient_desc",
  "video_views_desc",
];

function canUseStorage(): boolean {
  return typeof window !== "undefined";
}

export function readStoredNumber(key: string, fallback: number): number {
  if (!canUseStorage()) {
    return fallback;
  }

  const raw = localStorage.getItem(key);
  if (!raw) {
    return fallback;
  }

  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function writeStoredNumber(key: string, value: number): void {
  if (!canUseStorage()) {
    return;
  }

  localStorage.setItem(key, String(value));
}

export function readStoredUploadPeriod(fallback: RadarUploadPeriod): RadarUploadPeriod {
  if (!canUseStorage()) {
    return fallback;
  }

  const raw = localStorage.getItem(RADAR_FILTER_STORAGE_KEYS.uploadPeriod);
  if (raw && VALID_UPLOAD_PERIODS.includes(raw as RadarUploadPeriod)) {
    return raw as RadarUploadPeriod;
  }

  return fallback;
}

export function writeStoredUploadPeriod(value: RadarUploadPeriod): void {
  if (!canUseStorage()) {
    return;
  }

  localStorage.setItem(RADAR_FILTER_STORAGE_KEYS.uploadPeriod, value);
}

export function readStoredSortBy(
  fallback: ExplosiveChannelSortOption,
): ExplosiveChannelSortOption {
  if (!canUseStorage()) {
    return fallback;
  }

  const raw = localStorage.getItem(RADAR_FILTER_STORAGE_KEYS.sortBy);
  if (raw && VALID_SORT_OPTIONS.includes(raw as ExplosiveChannelSortOption)) {
    return raw as ExplosiveChannelSortOption;
  }

  return fallback;
}

export function writeStoredSortBy(value: ExplosiveChannelSortOption): void {
  if (!canUseStorage()) {
    return;
  }

  localStorage.setItem(RADAR_FILTER_STORAGE_KEYS.sortBy, value);
}

export function hasStoredUploadPeriod(): boolean {
  if (!canUseStorage()) {
    return false;
  }

  return localStorage.getItem(RADAR_FILTER_STORAGE_KEYS.uploadPeriod) !== null;
}
