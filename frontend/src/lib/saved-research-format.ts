import {
  canonicalYoutubeUrl,
  formatOptionalAge,
  formatOptionalSubscribers,
  formatOptionalViews,
  humanReasonsForDisplay,
} from "@/lib/attention-format";
import { formatDateTimeLocal, formatMonitoringVph } from "@/lib/monitoring-format";

import {
  CHANNEL_BASELINE_UNAVAILABLE,
  DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND,
  FAMILY_HISTORICAL_ANCHOR_SAVE_LABEL,
  MANUAL_SAVED_VIDEO_REFRESH_SOURCE,
  OBSERVATION_SOURCE_LABELS,
} from "./saved-research-labels";

export type ChannelRelativeView = {
  status: string;
  baseline_quality: string;
  comparable_video_count: number;
  vph_vs_channel_median: number | null;
  notes: string[];
};

export function youtubeWatchUrl(videoId: string, url?: string | null): string {
  return canonicalYoutubeUrl(videoId, url ?? undefined);
}

/** VPH value only (no trailing " VPH") — use beside a "VPH" label. */
export function formatVphValue(value: number | null | undefined): string | null {
  if (value == null || Number.isNaN(value)) {
    return null;
  }
  return formatMonitoringVph(value);
}

export function formatMetricOrUnavailable(
  formatted: string | null,
  unavailableLabel = "—",
): string {
  return formatted ?? unavailableLabel;
}

export function parseWinnerEvidence(
  evidence: unknown,
): Record<string, unknown> | null {
  if (!evidence || typeof evidence !== "object") {
    return null;
  }
  return evidence as Record<string, unknown>;
}

export function channelRelativeFromEvidence(
  evidence: Record<string, unknown> | null,
): ChannelRelativeView | null {
  if (!evidence) return null;
  const rel = evidence.channel_relative_signal;
  if (!rel || typeof rel !== "object") return null;
  const row = rel as Record<string, unknown>;
  return {
    status: String(row.status ?? "unavailable"),
    baseline_quality: String(row.baseline_quality ?? "none"),
    comparable_video_count: Number(row.comparable_video_count ?? 0),
    vph_vs_channel_median:
      row.vph_vs_channel_median == null
        ? null
        : Number(row.vph_vs_channel_median),
    notes: Array.isArray(row.notes)
      ? row.notes.map((n) => String(n))
      : [],
  };
}

export function formatChannelRelativeSummary(rel: ChannelRelativeView | null): string {
  if (!rel) {
    return CHANNEL_BASELINE_UNAVAILABLE;
  }
  if (rel.status === "unavailable" || rel.baseline_quality === "none") {
    return CHANNEL_BASELINE_UNAVAILABLE;
  }
  const ratio =
    rel.vph_vs_channel_median != null && !Number.isNaN(rel.vph_vs_channel_median)
      ? `${rel.vph_vs_channel_median.toFixed(2)}× медианы VPH канала`
      : "медиана VPH канала недоступна";
  const quality =
    rel.baseline_quality === "production_ready"
      ? "качество baseline: production"
      : `качество baseline: ${rel.baseline_quality}`;
  return `${ratio} · ${quality} · сопоставимых видео: ${rel.comparable_video_count}`;
}

export function frozenHumanReasons(frozen: Record<string, unknown>): string[] {
  const evidence = parseWinnerEvidence(frozen.evidence);
  if (!evidence) return [];
  const raw = evidence.human_reasons;
  if (!Array.isArray(raw)) return [];
  return humanReasonsForDisplay(raw.map(String));
}

export function familyLabelsFromContext(frozen: Record<string, unknown>): string[] {
  const ctx = frozen.context;
  if (!ctx || typeof ctx !== "object") return [];
  const memberships = (ctx as Record<string, unknown>).family_memberships;
  if (!Array.isArray(memberships)) return [];
  return memberships
    .map((m) =>
      m && typeof m === "object" && "label" in m ? String((m as { label: string }).label) : "",
    )
    .filter(Boolean);
}

export function formatObservationWhen(iso: string): string {
  return formatDateTimeLocal(iso);
}

export function observationSourceLabel(payload: Record<string, unknown> | undefined): string | null {
  if (!payload) return null;
  const kind = payload.observation_kind;
  if (kind === MANUAL_SAVED_VIDEO_REFRESH_SOURCE) {
    return OBSERVATION_SOURCE_LABELS[MANUAL_SAVED_VIDEO_REFRESH_SOURCE];
  }
  if (kind === DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND) {
    return OBSERVATION_SOURCE_LABELS[DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND];
  }
  if (payload.attention_run_id && kind !== MANUAL_SAVED_VIDEO_REFRESH_SOURCE) {
    return OBSERVATION_SOURCE_LABELS.attention_refresh;
  }
  return null;
}

export function isDailyIntelligenceAnchorPayload(
  payload: Record<string, unknown> | undefined,
): boolean {
  return payload?.observation_kind === DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND;
}

export function videoObservationAttentionLabel(
  row: { video_present_in_attention: boolean; payload?: Record<string, unknown> },
): string {
  const payload = row.payload;
  if (
    isDailyIntelligenceAnchorPayload(payload) ||
    payload?.present_in_daily_intelligence_edition === true
  ) {
    return "историческая edition Daily Intelligence";
  }
  return row.video_present_in_attention ? "в текущей выборке Attention" : "не в текущей выборке Attention";
}

export function familyHistoricalAnchorCounts(
  payload: Record<string, unknown> | undefined,
): { video_count: number | null; channel_count: number | null } {
  if (!payload) {
    return { video_count: null, channel_count: null };
  }
  const counts = payload.counts as Record<string, unknown> | undefined;
  const family = payload.family as Record<string, unknown> | undefined;
  const videoRaw = counts?.video_count ?? family?.video_count;
  const channelRaw = counts?.channel_count ?? family?.channel_count;
  return {
    video_count: typeof videoRaw === "number" ? videoRaw : null,
    channel_count: typeof channelRaw === "number" ? channelRaw : null,
  };
}

/** Source line for family observation history / detail (not a live Attention refresh). */
export function familyObservationSourceLabel(
  payload: Record<string, unknown> | undefined,
): string | null {
  if (isDailyIntelligenceAnchorPayload(payload)) {
    return FAMILY_HISTORICAL_ANCHOR_SAVE_LABEL;
  }
  return observationSourceLabel(payload);
}

export function familyObservationPresenceLabel(row: {
  family_present: boolean;
  payload?: Record<string, unknown>;
  absence_message?: string | null;
}): string {
  if (isDailyIntelligenceAnchorPayload(row.payload)) {
    return FAMILY_HISTORICAL_ANCHOR_SAVE_LABEL;
  }
  if (row.family_present) {
    return "в текущей выборке Attention";
  }
  return row.absence_message ?? "Тема не в текущей выборке Attention.";
}

export function isManualObservationPayload(payload: Record<string, unknown> | undefined): boolean {
  return payload?.observation_kind === MANUAL_SAVED_VIDEO_REFRESH_SOURCE;
}

export function deltaLabel(before: number | null, after: number | null): string | null {
  if (before == null || after == null) return null;
  const d = after - before;
  if (d === 0) return "без изменения";
  return d > 0 ? `+${d.toLocaleString("ru-RU")}` : d.toLocaleString("ru-RU");
}
