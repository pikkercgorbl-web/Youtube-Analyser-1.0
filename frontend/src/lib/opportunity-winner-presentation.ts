import {
  formatOptionalVph,
  humanReasonsForDisplay,
  snapshotFreshnessLabel,
  windowHoursLabel,
} from "@/lib/attention-format";
import type {
  AttentionChannelMomentum,
  AttentionChannelRelativeSignal,
  AttentionSummary,
  AttentionVideoWinner,
} from "@/lib/attention-types";
import { classifyChannelMomentum } from "@/lib/channel-momentum-presentation";
import { formatDateTimeLocal, formatMonitoringVph } from "@/lib/monitoring-format";
import { parseWinnerEvidence } from "@/lib/saved-research-format";

export type WinnerInsightBlock = {
  key: "why" | "channel" | "next" | "period";
  label: string;
  short: string;
  detail: string;
};

/** Confirmed headline from reason codes + metrics (not title/thumbnail). */
export function buildWinnerWhyHereBlock(video: AttentionVideoWinner): WinnerInsightBlock {
  const codes = new Set(video.reason_codes ?? []);
  const vph = formatOptionalVph(video.vph);

  if (video.breakout_rank != null && codes.has("breakout_high_rank")) {
    return {
      key: "why",
      label: "Почему здесь",
      short: `Radar №${video.breakout_rank}`,
      detail: vph
        ? `${vph} в окне Attention (рейтинг breakout_v1).`
        : "Высокий рейтинг breakout_v1 в текущем окне Attention.",
    };
  }
  if (codes.has("high_current_vph") && video.vph != null) {
    return {
      key: "why",
      label: "Почему здесь",
      short: "VPH в топ‑25%",
      detail: `${vph ?? "—"} среди eligible видео этого окна (порог — 75‑й перцентиль).`,
    };
  }
  if (codes.has("accelerating_velocity")) {
    return {
      key: "why",
      label: "Почему здесь",
      short: "Ускорение",
      detail:
        "Средний темп просмотров вырос по серии снимков мониторинга (≥3 точки, последняя ≥2× первой).",
    };
  }
  if (codes.has("confirmed_72h_growth")) {
    const growth =
      video.delayed_outcome_growth != null
        ? `+${video.delayed_outcome_growth.toLocaleString("ru-RU")} просмотров`
        : "рост подтверждён";
    return {
      key: "why",
      label: "Почему здесь",
      short: "Рост 72 ч",
      detail: `Горизонт 72 ч: ${growth} относительно момента обнаружения.`,
    };
  }
  if (codes.has("channel_relative_outlier") && video.channel_relative_signal?.baseline_quality === "production_ready") {
    return {
      key: "why",
      label: "Почему здесь",
      short: "Сильнее канала",
      detail: "VPH ≥2× медианы сопоставимых роликов канала (production-ready baseline).",
    };
  }

  const human = humanReasonsForDisplay(video.human_reasons);
  if (human.length > 0) {
    return {
      key: "why",
      label: "Почему здесь",
      short: "Сигнал Radar",
      detail: human[0],
    };
  }

  return {
    key: "why",
    label: "Почему здесь",
    short: "В подборке",
    detail: "Видео в текущем снимке Winners; текст причин в снимке не сохранён.",
  };
}

export function buildWinnerChannelBlock(video: AttentionVideoWinner): WinnerInsightBlock {
  const rel = video.channel_relative_signal;
  if (!rel || rel.status === "unavailable" || rel.baseline_quality === "none") {
    const count = rel?.comparable_video_count ?? 0;
    let detail =
      "Radar сравнивает VPH с недавними роликами канала на похожем возрасте — снимков в окне Attention недостаточно.";
    if (count === 1) {
      detail = "Найден только 1 сопоставимый ролик — коэффициент к медиане не показываем.";
    } else if (count === 0) {
      detail = "Нет сопоставимых роликов в окне Attention — это ограничение данных, не оценка канала.";
    }
    return {
      key: "channel",
      label: "На своём канале",
      short: "Пока мало данных",
      detail,
    };
  }

  const count = rel.comparable_video_count;
  if (count <= 1) {
    return {
      key: "channel",
      label: "На своём канале",
      short: "Пока мало данных",
      detail: "Найден только 1 сопоставимый ролик — коэффициент к медиане не показываем.",
    };
  }

  const ratio =
    rel.vph_vs_channel_median != null && !Number.isNaN(rel.vph_vs_channel_median)
      ? rel.vph_vs_channel_median
      : null;

  if (rel.baseline_quality === "diagnostic") {
    return {
      key: "channel",
      label: "На своём канале",
      short: "Ориентир",
      detail:
        ratio != null
          ? `~${ratio.toFixed(2)}× медианы VPH по ${count} роликам — предварительно, мало сопоставимых снимков.`
          : `${count} сопоставимых ролика — отношение к медиане не посчитано.`,
    };
  }

  if (rel.baseline_quality === "production_ready" && ratio != null) {
    const stronger = ratio >= 1.05;
    return {
      key: "channel",
      label: "На своём канале",
      short: stronger ? "Сильнее нормы" : "Около нормы",
      detail: `${ratio.toFixed(2)}× медианы VPH канала (${count} сопоставимых роликов в окне).`,
    };
  }

  return {
    key: "channel",
    label: "На своём канале",
    short: "Пока мало данных",
    detail: "Сравнение с каналом в снимке не готово.",
  };
}

export function buildWinnerNextBlock(
  video: AttentionVideoWinner,
  options?: { relatedFamilyCount?: number },
): WinnerInsightBlock {
  const rel = video.channel_relative_signal;
  const weakChannel =
    !rel ||
    rel.status === "unavailable" ||
    rel.baseline_quality === "none" ||
    rel.comparable_video_count <= 1;

  if (weakChannel || video.acceleration_state !== "accelerating") {
    return {
      key: "next",
      label: "Что дальше",
      short: "Динамика",
      detail: "Откройте график снимков мониторинга — проверьте, держится ли темп просмотров.",
    };
  }

  if ((options?.relatedFamilyCount ?? 0) > 0) {
    return {
      key: "next",
      label: "Что дальше",
      short: "Подборки",
      detail: "Посмотрите связанные family в карточке — там контекст повторяющихся идей.",
    };
  }

  if ((video.discovery_keywords?.length ?? 0) > 0) {
    return {
      key: "next",
      label: "Что дальше",
      short: "Запросы",
      detail: "Раскройте «Где найдено» — по каким поисковым запросам Radar увидел видео.",
    };
  }

  return {
    key: "next",
    label: "Что дальше",
    short: "Сохранить",
    detail: "Сохраните видео в исследования, чтобы вернуться к метрикам после следующего снимка.",
  };
}

export function buildWinnerInsightBlocks(
  video: AttentionVideoWinner,
  options?: { relatedFamilyCount?: number },
): WinnerInsightBlock[] {
  return [
    buildWinnerWhyHereBlock(video),
    buildWinnerChannelBlock(video),
    buildWinnerNextBlock(video, options),
  ];
}

export type VideoSignalInput = {
  reason_codes?: string[];
  vph?: number | null;
  breakout_rank?: number | null;
  acceleration_state?: string | null;
  delayed_outcome_state?: string | null;
  channel_relative_signal?: AttentionChannelRelativeSignal | null;
};

export type VideoHighlightSnapshot = {
  headline: string;
  detail: string | null;
};

export type FrozenVideoHighlightView =
  | { kind: "highlight"; headline: string; detail: string | null }
  | { kind: "manual" }
  | { kind: "none" };

export function videoSignalInputFromWinner(video: AttentionVideoWinner): VideoSignalInput {
  return {
    reason_codes: video.reason_codes,
    vph: video.vph,
    breakout_rank: video.breakout_rank,
    acceleration_state: video.acceleration_state,
    delayed_outcome_state: video.delayed_outcome_state,
    channel_relative_signal: video.channel_relative_signal,
  };
}

export function videoSignalInputFromEvidence(
  evidence: Record<string, unknown> | null,
): VideoSignalInput {
  if (!evidence) {
    return {};
  }
  const relRaw = evidence.channel_relative_signal;
  let channel_relative_signal: AttentionChannelRelativeSignal | null = null;
  if (relRaw && typeof relRaw === "object") {
    const row = relRaw as Record<string, unknown>;
    channel_relative_signal = {
      status: String(row.status ?? "unavailable"),
      baseline_quality: String(row.baseline_quality ?? "none"),
      comparable_video_count: Number(row.comparable_video_count ?? 0),
      vph_vs_channel_median:
        row.vph_vs_channel_median == null ? null : Number(row.vph_vs_channel_median),
      notes: Array.isArray(row.notes) ? row.notes.map((n) => String(n)) : [],
    };
  }
  return {
    reason_codes: Array.isArray(evidence.reason_codes)
      ? evidence.reason_codes.map((c) => String(c))
      : [],
    vph: evidence.vph == null ? null : Number(evidence.vph),
    breakout_rank:
      evidence.breakout_rank == null ? null : Number(evidence.breakout_rank),
    acceleration_state:
      evidence.acceleration_state != null ? String(evidence.acceleration_state) : null,
    delayed_outcome_state:
      evidence.delayed_outcome_state != null
        ? String(evidence.delayed_outcome_state)
        : null,
    channel_relative_signal,
  };
}

function formatVphPerHourLine(vph: number | null | undefined): string | null {
  if (vph == null || Number.isNaN(vph)) {
    return null;
  }
  return `${formatMonitoringVph(vph)} просмотров/час`;
}

export function channelRelativeHighlightEligible(input: VideoSignalInput): boolean {
  const codes = new Set(input.reason_codes ?? []);
  const rel = input.channel_relative_signal;
  if (!codes.has("channel_relative_outlier") || !rel) {
    return false;
  }
  if (rel.baseline_quality !== "production_ready") {
    return false;
  }
  if ((rel.comparable_video_count ?? 0) < 2) {
    return false;
  }
  const ratio = rel.vph_vs_channel_median;
  return ratio != null && !Number.isNaN(ratio) && ratio >= 1.05;
}

export function buildVideoHighlightSnapshot(
  input: VideoSignalInput,
): VideoHighlightSnapshot | null {
  const codes = new Set(input.reason_codes ?? []);

  if (codes.has("breakout_high_rank") && input.breakout_rank != null) {
    const detailParts: string[] = [];
    const vphLine = formatVphPerHourLine(input.vph);
    if (vphLine) {
      detailParts.push(vphLine);
    }
    if (codes.has("high_current_vph")) {
      detailParts.push("В топ-25% выборки");
    }
    return {
      headline: `Radar №${input.breakout_rank}`,
      detail: detailParts.length > 0 ? detailParts.join(" · ") : null,
    };
  }

  if (codes.has("high_current_vph") && input.vph != null) {
    const vphLine = formatVphPerHourLine(input.vph);
    return {
      headline: "Высокий темп",
      detail: vphLine ? `${vphLine} · В топ-25% выборки` : "В топ-25% выборки",
    };
  }

  if (codes.has("accelerating_velocity") && input.acceleration_state === "accelerating") {
    const vphLine = formatVphPerHourLine(input.vph);
    return {
      headline: "Набирает скорость",
      detail: vphLine ?? "Рост темпа по серии снимков мониторинга",
    };
  }

  if (channelRelativeHighlightEligible(input)) {
    const ratio = input.channel_relative_signal!.vph_vs_channel_median!;
    const formatted = ratio.toLocaleString("ru-RU", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    return {
      headline: "Выше нормы канала",
      detail: `${formatted}× медианы VPH канала`,
    };
  }

  if (codes.has("confirmed_72h_growth")) {
    return {
      headline: "Рост 72 ч",
      detail: "Подтверждённый рост просмотров после обнаружения",
    };
  }

  return null;
}

export function frozenVideoHighlightFromPayload(
  frozen: Record<string, unknown>,
): FrozenVideoHighlightView {
  const evidence = parseWinnerEvidence(frozen.evidence);
  if (!evidence) {
    return { kind: "none" };
  }
  const input = videoSignalInputFromEvidence(evidence);
  const snapshot = buildVideoHighlightSnapshot(input);
  if (snapshot) {
    return { kind: "highlight", headline: snapshot.headline, detail: snapshot.detail };
  }
  const codes = input.reason_codes ?? [];
  if (evidence.from_canonical_video === true || codes.length === 0) {
    return { kind: "manual" };
  }
  return { kind: "none" };
}

const OPPORTUNITY_BADGE_LABELS = {
  highVph: "Высокий темп",
  accelerating: "Набирает скорость",
  aboveChannel: "Выше нормы канала",
  channelGrowth: "Рост канала",
} as const;

export function pickOpportunityVideoBadges(
  video: AttentionVideoWinner,
  channelMomentum: AttentionChannelMomentum[] = [],
): string[] {
  const input = videoSignalInputFromWinner(video);
  const codes = new Set(input.reason_codes ?? []);
  const badges: string[] = [];

  if (codes.has("high_current_vph") && input.vph != null) {
    badges.push(OPPORTUNITY_BADGE_LABELS.highVph);
  }
  if (codes.has("accelerating_velocity") && input.acceleration_state === "accelerating") {
    badges.push(OPPORTUNITY_BADGE_LABELS.accelerating);
  }
  if (channelRelativeHighlightEligible(input)) {
    badges.push(OPPORTUNITY_BADGE_LABELS.aboveChannel);
  }

  const momentumByChannel = new Map(
    channelMomentum.map((row) => [row.channel_id, row] as const),
  );
  const ch = momentumByChannel.get(video.channel_id);
  if (ch && classifyChannelMomentum(ch) === "confirmed_growth") {
    badges.push(OPPORTUNITY_BADGE_LABELS.channelGrowth);
  }

  return badges.slice(0, 2);
}

export type AttentionSnapshotContext = {
  computedAt: string | null;
  windowHours: number | null;
  windowStart: string | null;
  windowEnd: string | null;
};

export function formatWinnerSnapshotContextLine(
  ctx: AttentionSnapshotContext,
  nowMs: number = Date.now(),
): string {
  const parts: string[] = [];
  if (ctx.computedAt) {
    parts.push(`Снимок Attention: ${formatDateTimeLocal(ctx.computedAt)} (${snapshotFreshnessLabel(ctx.computedAt, nowMs)})`);
  } else {
    parts.push("Снимок Attention: время неизвестно");
  }
  if (ctx.windowHours != null) {
    parts.push(windowHoursLabel(ctx.windowHours));
  }
  if (ctx.windowStart && ctx.windowEnd) {
    parts.push(
      `Окно данных ${formatDateTimeLocal(ctx.windowStart)} — ${formatDateTimeLocal(ctx.windowEnd)}`,
    );
  }
  parts.push("Показатели VPH и сравнение — по снимку, не по дате публикации ролика.");
  return parts.join(" · ");
}

export function snapshotContextFromSummary(
  summary: AttentionSummary | null,
  computedAt: string | null,
): AttentionSnapshotContext {
  if (!summary) {
    return {
      computedAt,
      windowHours: null,
      windowStart: null,
      windowEnd: null,
    };
  }
  return {
    computedAt: computedAt ?? summary.computed_at,
    windowHours: summary.window_hours,
    windowStart: summary.window_start,
    windowEnd: summary.window_end,
  };
}
