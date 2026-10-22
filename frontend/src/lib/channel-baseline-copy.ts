import type { AttentionChannelRelativeSignal } from "@/lib/attention-types";
import type { ChannelRelativeView } from "@/lib/saved-research-format";

export type ChannelRelativeLike =
  | ChannelRelativeView
  | AttentionChannelRelativeSignal
  | null
  | undefined;

export type ChannelBaselineExplanation = {
  headline: string;
  body: string;
  limitation: string | null;
  dataTestId: "baseline-available" | "baseline-unavailable";
};

function comparablePhrase(count: number): string {
  if (count <= 0) {
    return "нет сопоставимых прошлых роликов в окне Attention";
  }
  if (count === 1) {
    return "1 прошлый ролик канала с близким возрастом";
  }
  return `${count} прошлых роликов канала с близким возрастом`;
}

/** Human copy for channel-relative signal; unavailable ≠ «плохой канал». */
export function formatChannelBaselineExplanation(
  rel: ChannelRelativeLike,
): ChannelBaselineExplanation {
  if (!rel || rel.status === "unavailable" || rel.baseline_quality === "none") {
    const notes = rel?.notes?.length ? rel.notes.join(" ") : null;
    return {
      headline: "Сравнение с каналом пока недоступно",
      body:
        "Radar сравнивает VPH этого ролика с недавними видео того же канала на похожем возрасте (по снимкам в окне Attention). " +
        "Сейчас таких измерений недостаточно — это ограничение данных, а не оценка качества канала.",
      limitation: notes,
      dataTestId: "baseline-unavailable",
    };
  }

  const compared = comparablePhrase(rel.comparable_video_count);
  const ratio =
    rel.vph_vs_channel_median != null && !Number.isNaN(rel.vph_vs_channel_median)
      ? `${rel.vph_vs_channel_median.toFixed(2)}× медианы VPH канала`
      : null;

  const qualityNote =
    rel.baseline_quality === "production_ready"
      ? "Достаточно сопоставимых снимков для уверенного сравнения."
      : rel.baseline_quality === "diagnostic"
        ? "Сравнение ориентировочное: мало сопоставимых роликов."
        : null;

  const bodyParts = [
    `С чем сравниваем: ${compared} (снимки мониторинга в окне Attention, не вся история канала).`,
    ratio ? `Результат: ${ratio}.` : "Отношение к медиане VPH канала не посчитано.",
    qualityNote,
  ].filter(Boolean);

  return {
    headline: "Сравнение с недавними роликами канала",
    body: bodyParts.join(" "),
    limitation: rel.notes?.length ? rel.notes.join(" ") : null,
    dataTestId: "baseline-available",
  };
}
