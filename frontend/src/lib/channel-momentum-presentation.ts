import { formatOptionalVph } from "@/lib/attention-format";
import type {
  AttentionChannelMomentum,
  AttentionChannelRepresentativeVideo,
} from "@/lib/attention-types";

export type ChannelMomentumCategory =
  | "confirmed_growth"
  | "strong_outliers"
  | "insufficient_data";

export type ChannelMomentumHeadline = {
  category: ChannelMomentumCategory;
  title: string;
  hint: string | null;
};

/** UI-only: backend publishes a channel when ≥2 recent videos each ≥ improvement_ratio_threshold× previous median VPH (default 1.5×); median ratio has no publish threshold. */
export const CHANNEL_MOMENTUM_MEDIAN_GROWTH_UI_RATIO = 1.05;

const CATEGORY_HEADLINE: Record<
  ChannelMomentumCategory,
  { title: string; hint: string | null }
> = {
  confirmed_growth: {
    title: "Есть сигнал роста",
    hint: "Медиана темпа новых роликов выше прежней; в снимке Attention также выполнено условие ≥2 сильных роликов.",
  },
  strong_outliers: {
    title: "Отдельные сильные ролики",
    hint: "Медиана новых роликов не выше прежней — сигнал от отдельных удачных публикаций.",
  },
  insufficient_data: {
    title: "Недостаточно данных",
    hint: "Сравнение на ~24 ч после публикации пока ненадёжно.",
  },
};

/** Backend lists channels with ≥2 recent videos each ≥ threshold× previous median VPH; median ratio may still be <1. */
export function classifyChannelMomentum(
  channel: AttentionChannelMomentum,
): ChannelMomentumCategory {
  const recentMeas = channel.recent_measurable_count ?? 0;
  const previousMeas = channel.previous_measurable_count ?? 0;
  const improving = channel.recent_improvement_count ?? 0;

  if (channel.previous_baseline_zero) {
    return "insufficient_data";
  }
  if (recentMeas < 2 || previousMeas < 2) {
    return "insufficient_data";
  }
  if (improving < 2) {
    return "insufficient_data";
  }

  const ratio = channel.recent_median_vph_vs_previous;
  if (ratio != null && ratio >= CHANNEL_MOMENTUM_MEDIAN_GROWTH_UI_RATIO) {
    return "confirmed_growth";
  }
  return "strong_outliers";
}

export function channelMomentumHeadline(
  channel: AttentionChannelMomentum,
): ChannelMomentumHeadline {
  const category = classifyChannelMomentum(channel);
  const base = CATEGORY_HEADLINE[category];
  return { category, title: base.title, hint: base.hint };
}

export function formatChannelComparisonLine(channel: AttentionChannelMomentum): string {
  const horizon = channel.momentum_horizon_hours ?? 24;
  const recentN = channel.recent_measurable_count ?? channel.recent_eligible_count ?? channel.recent_video_count;
  const previousN =
    channel.previous_measurable_count ?? channel.previous_eligible_count ?? channel.previous_video_count;
  return `Сравнили ${recentN} новых с ${previousN} предыдущими роликами около ${horizon} часов после публикации.`;
}

export function channelMomentumCategoryCounts(
  channels: AttentionChannelMomentum[],
): Record<ChannelMomentumCategory, number> {
  const counts: Record<ChannelMomentumCategory, number> = {
    confirmed_growth: 0,
    strong_outliers: 0,
    insufficient_data: 0,
  };
  for (const ch of channels) {
    counts[classifyChannelMomentum(ch)] += 1;
  }
  return counts;
}

export function formatCategoryCountsSummary(
  counts: Record<ChannelMomentumCategory, number>,
): string {
  const parts: string[] = [];
  if (counts.confirmed_growth > 0) {
    parts.push(`${counts.confirmed_growth} с сигналом роста`);
  }
  if (counts.strong_outliers > 0) {
    parts.push(`${counts.strong_outliers} с отдельными сильными роликами`);
  }
  if (counts.insufficient_data > 0) {
    parts.push(`${counts.insufficient_data} с недостаточными данными`);
  }
  return parts.length ? parts.join(" · ") : "Нет каналов с сигналом в этом снимке";
}

export type ChannelEvidenceVideo = {
  video_id: string;
  title: string;
  vphLabel: string | null;
  metricCaption: string | null;
  youtube_url: string;
};

const UNAVAILABLE_REASON_RU: Record<string, string> = {
  video_not_in_db: "нет строки Video в БД",
  published_at_unusable: "дата публикации не пригодна для сравнения",
  no_snapshots_in_db: "нет снимков VideoSnapshot",
  no_snapshot_near_horizon: "нет снимка около целевого возраста",
};

export function formatRepresentativeMetricCaption(
  rep: AttentionChannelRepresentativeVideo,
): string | null {
  if (rep.horizon_vph == null) {
    return null;
  }
  const horizon = rep.target_horizon_hours ?? 24;
  const age =
    rep.actual_age_hours != null ? ` (~${rep.actual_age_hours.toFixed(1)} ч)` : "";
  const vph = formatOptionalVph(rep.horizon_vph);
  const source =
    rep.measurement_source === "attention_snapshot_frozen"
      ? "на снимке Attention"
      : rep.measurement_source === "video_snapshot_replay_before_attention"
        ? "по VideoSnapshot в БД на момент публикации Attention"
        : "по VideoSnapshot в БД";
  let line = `VPH ${vph} ${source}, около ${horizon} ч после публикации${age}`;
  if (rep.vs_previous_median_ratio != null) {
    line += ` · ${rep.vs_previous_median_ratio.toFixed(2)}× к медиане прежнего периода`;
  }
  return line;
}

export type ChannelEvidencePick = {
  /** Rows with title from the frozen Winners snapshot only. */
  videos: ChannelEvidenceVideo[];
  representativeCount: number;
  /** representative ids not present in Winners lookup (no title/VPH in this API). */
  missingFromWinnersCount: number;
};

export function pickEvidenceVideos(
  channel: AttentionChannelMomentum,
  limit = 3,
): ChannelEvidencePick {
  const reps = (channel.representative_videos ?? []).slice(0, limit);
  const ids = channel.representative_video_ids.slice(0, limit);
  const videos: ChannelEvidenceVideo[] = [];
  let missingFromWinnersCount = 0;
  for (const rep of reps) {
    if (rep.horizon_vph == null) {
      missingFromWinnersCount += 1;
      continue;
    }
    const title = rep.title?.trim() || rep.video_id;
    videos.push({
      video_id: rep.video_id,
      title,
      vphLabel: formatOptionalVph(rep.horizon_vph),
      metricCaption: formatRepresentativeMetricCaption(rep),
      youtube_url: rep.youtube_url,
    });
  }
  if (reps.length === 0 && ids.length > 0) {
    missingFromWinnersCount = ids.length;
  }
  return {
    videos,
    representativeCount: reps.length > 0 ? reps.length : ids.length,
    missingFromWinnersCount,
  };
}

export function formatEvidenceUnavailableMessage(
  pick: ChannelEvidencePick,
  channel: AttentionChannelMomentum,
): string | null {
  if (pick.representativeCount === 0) {
    return "Примеры роликов в снимке не привязаны — откройте «Анализ канала» для деталей.";
  }
  if (pick.videos.length > 0) {
    return null;
  }
  const reps = channel.representative_videos ?? [];
  const reasons = [
    ...new Set(
      reps
        .map((r) => r.unavailable_reason)
        .filter(Boolean)
        .map((code) => UNAVAILABLE_REASON_RU[code as string] ?? code),
    ),
  ];
  const reasonText = reasons.length ? ` Причина: ${reasons.join("; ")}.` : "";
  return `Для ${pick.representativeCount} опорных роликов нет age-aligned VPH на ~${channel.momentum_horizon_hours ?? 24} ч в БД.${reasonText} Подробности — в «Как рассчитано».`;
}

/** Raw diagnostics for «Как рассчитано» — dedupe incomplete-history lines. */
export function buildChannelCalculationDetails(
  channel: AttentionChannelMomentum,
): string[] {
  const lines: string[] = [];
  const horizon = channel.momentum_horizon_hours ?? 24;
  const tolerance = channel.momentum_horizon_tolerance_hours ?? 6;
  const threshold = channel.improvement_ratio_threshold ?? 1.5;

  lines.push(
    `Окно: ${channel.recent_window_days} дн. (новые) / ${channel.previous_window_days} дн. (предыдущие).`,
  );
  lines.push(`Возраст снимка: ~${horizon} ч (±${tolerance} ч) после публикации.`);
  lines.push(
    `Порог сильного ролика: VPH ≥ ${threshold}× медианы предыдущего периода (${formatOptionalVph(channel.previous_median_vph) ?? "—"}).`,
  );
  if (channel.recent_median_vph != null) {
    lines.push(`Медиана VPH новых: ${formatOptionalVph(channel.recent_median_vph)}.`);
  }
  if (channel.recent_median_vph_vs_previous != null) {
    lines.push(`Отношение медиан (новые / прежние): ${channel.recent_median_vph_vs_previous.toFixed(2)}×.`);
  }
  lines.push(
    `Роликов с порогом улучшения: ${channel.recent_improvement_count ?? "—"} из ${channel.recent_measurable_count ?? "—"} измеренных новых.`,
  );
  if (channel.representative_video_ids.length > 0) {
    lines.push(
      `ID опорных роликов (из снимка Attention): ${channel.representative_video_ids.join(", ")}.`,
    );
  }

  const incompleteness = new Set<string>();
  for (const note of channel.incompleteness_notes ?? []) {
    incompleteness.add(note.trim());
  }
  for (const raw of channel.human_reasons ?? []) {
    const text = raw.trim();
    if (!text) continue;
    if (text.toLowerCase().startsWith("incomplete history:")) {
      incompleteness.add(text.replace(/^Incomplete history:\s*/i, "").trim());
      continue;
    }
    if (text.toLowerCase().startsWith("context:")) {
      lines.push(text);
      continue;
    }
    lines.push(text);
  }
  for (const note of incompleteness) {
    if (note) {
      lines.push(`Неполная история: ${note}`);
    }
  }

  return [...new Set(lines)];
}

export function channelFaceSampleWarning(channel: AttentionChannelMomentum): string | null {
  const recentMeas = channel.recent_measurable_count ?? 0;
  const previousMeas = channel.previous_measurable_count ?? 0;
  if ((channel.incompleteness_notes?.length ?? 0) > 0) {
    return "Есть пропуски в снимках на нужном возрасте — вывод предварительный.";
  }
  if (recentMeas <= 2 || previousMeas <= 2) {
    return "Мало сопоставимых роликов — трактуйте осторожно.";
  }
  return null;
}
