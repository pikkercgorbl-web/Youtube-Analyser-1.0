import {
  canonicalYoutubeUrl,
  formatOptionalAge,
  formatOptionalSubscribers,
  formatOptionalViews,
  formatOptionalVph,
  groupingSourceLabel,
  humanReasonsForDisplay,
} from "@/lib/attention-format";
import { formatDateTimeLocal } from "@/lib/monitoring-format";

export const FROZEN_EVIDENCE_SOURCE =
  "Замороженный payload Attention на момент публикации отчёта";

export const APPEARANCE_RUN_SOURCE =
  "Появление в run Attention (может не совпадать с итоговой daily edition)";

export const DAILY_EDITION_SOURCE =
  "Итоговая daily edition за выбранный UTC-день";

export function displayOrMissing(
  formatted: string | null | undefined,
): string {
  if (formatted == null || formatted === "") {
    return "Нет данных";
  }
  return formatted;
}

export function displayOptionalNumber(
  value: number | null | undefined,
  formatter: (v: number) => string | null,
): string {
  if (value == null || Number.isNaN(value)) {
    return "Нет данных";
  }
  return displayOrMissing(formatter(value));
}

export function formatWinnerMetrics(evidence: Record<string, unknown>) {
  return {
    views: displayOptionalNumber(evidence.views as number | null, (v) =>
      formatOptionalViews(v),
    ),
    vph: displayOptionalNumber(evidence.vph as number | null, (v) =>
      formatOptionalVph(v),
    ),
    ageHours: displayOptionalNumber(evidence.age_hours as number | null, (v) =>
      formatOptionalAge(v),
    ),
    subscribers: displayOptionalNumber(
      evidence.subscribers as number | null,
      (v) => formatOptionalSubscribers(v),
    ),
    acceleration: formatAccelerationState(evidence.acceleration_state),
    breakoutRank:
      evidence.breakout_rank != null
        ? `#${evidence.breakout_rank}`
        : "Нет данных",
    breakoutEligible:
      typeof evidence.breakout_eligible === "boolean"
        ? evidence.breakout_eligible
          ? "Да"
          : "Нет"
        : "Нет данных",
    delayedOutcomeState: formatDelayedOutcomeState(
      evidence.delayed_outcome_state,
    ),
    delayedOutcomeGrowth:
      evidence.delayed_outcome_growth != null
        ? String(evidence.delayed_outcome_growth)
        : "Нет данных",
    humanReasons: humanReasonsForDisplay(
      (evidence.human_reasons as string[] | undefined) ?? [],
    ),
    reasonCodes: (evidence.reason_codes as string[] | undefined) ?? [],
  };
}

function formatAccelerationState(value: unknown): string {
  if (value == null || value === "") {
    return "Нет данных";
  }
  return String(value);
}

function formatDelayedOutcomeState(value: unknown): string {
  if (value == null || value === "") {
    return "Нет данных";
  }
  const s = String(value);
  if (s === "unknown" || s === "not_applicable") {
    return "Нет данных";
  }
  return s;
}

export function formatChannelRelativeBlock(
  signal: unknown,
): { lines: string[]; hasData: boolean } {
  if (!signal || typeof signal !== "object") {
    return { lines: [], hasData: false };
  }
  const s = signal as Record<string, unknown>;
  const lines: string[] = [];
  if (s.status != null) lines.push(`Статус: ${String(s.status)}`);
  if (s.baseline_quality != null)
    lines.push(`Качество baseline: ${String(s.baseline_quality)}`);
  if (s.comparable_video_count != null)
    lines.push(`Сопоставимых видео: ${String(s.comparable_video_count)}`);
  if (s.vph_vs_channel_median != null)
    lines.push(`VPH vs медиана канала: ${String(s.vph_vs_channel_median)}`);
  const notes = s.notes as string[] | undefined;
  if (notes?.length) {
    notes.forEach((n) => lines.push(n));
  }
  return { lines, hasData: lines.length > 0 };
}

export function formatDiscoveryProvenance(prov: Record<string, unknown>): {
  summary: string;
  details: string[];
} {
  if (!prov || Object.keys(prov).length === 0) {
    return { summary: "Нет данных", details: [] };
  }
  if (prov.available === false) {
    const reason = prov.reason ? String(prov.reason) : "недоступно";
    return {
      summary: `Provenance недоступен (${reason})`,
      details: objectToDetailLines(prov),
    };
  }
  if (prov.available === true) {
    return {
      summary: "Discovery provenance сохранён",
      details: objectToDetailLines(prov),
    };
  }
  return { summary: "Нет данных", details: objectToDetailLines(prov) };
}

function objectToDetailLines(obj: Record<string, unknown>): string[] {
  return Object.entries(obj)
    .filter(([, v]) => v != null && v !== "")
    .map(([k, v]) => {
      if (k === "discovered_at" && typeof v === "string") {
        return `${k}: ${formatDateTimeLocal(v)}`;
      }
      return `${k}: ${String(v)}`;
    });
}

export const FAMILY_QUALITY_FLAG_EXPLANATIONS: Record<
  string,
  { title: string; body: string }
> = {
  keyword_only: {
    title: "keyword_only",
    body:
      "Группа опирается в основном на общий ключевой запрос. Это не доказанный тренд и не гарантия монетизации.",
  },
  broad_keyword_group: {
    title: "broad_keyword_group",
    body:
      "Широкий ключевой запрос объединяет разнородные ролики. Требуется ручная проверка смысла группы.",
  },
  phrase_supported: {
    title: "phrase_supported",
    body:
      "Есть поддержка повторяющейся фразы в названиях. Совпадение формулировок ≠ повторяемый успех.",
  },
  topic_supported: {
    title: "topic_supported",
    body:
      "Есть поддержка общей темы между роликами. Тема может быть слишком широкой для выводов.",
  },
  cross_source_supported: {
    title: "cross_source_supported",
    body:
      "Сигнал подкреплён несколькими источниками группировки. Это повышает связность группы, но не прогноз результата.",
  },
};

export function familyKindLabel(familyKind: unknown): string {
  if (typeof familyKind !== "string" || !familyKind) {
    return "Нет данных";
  }
  return groupingSourceLabel(familyKind);
}

export function youtubeLinksForVideoIds(ids: string[]): { id: string; url: string }[] {
  return ids.map((id) => ({ id, url: canonicalYoutubeUrl(id) }));
}
