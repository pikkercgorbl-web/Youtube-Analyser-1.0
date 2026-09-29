import type { SummaryLine, SummaryTone } from "@/components/design-system/summary-strip";
import type { KeywordPerformanceMetrics } from "@/lib/keyword-performance-types";

import { formatCount } from "@/lib/operations-format";

export type KeywordListSummary = {
  tone: SummaryTone;
  lines: SummaryLine[];
};

export function discoveryListSummary(items: KeywordPerformanceMetrics[]): KeywordListSummary {
  if (items.length === 0) {
    return {
      tone: "neutral",
      lines: [{ text: "Нет ключей в текущей выборке.", emphasis: true }],
    };
  }

  const keywordCount = items.length;
  const uniqueVideos = items.reduce((s, r) => s + (r.unique_video_count ?? 0), 0);
  const earlyEvidence = items.filter((r) => r.evidence_status === "early" || r.evidence_status === "insufficient").length;
  const singleScan = items.filter((r) => r.scan_count <= 1).length;

  const lines: SummaryLine[] = [
    {
      text: `${formatCount(keywordCount)} ключей в выборке. ${formatCount(uniqueVideos)} уникальных видео найдено.`,
      emphasis: true,
    },
  ];

  if (earlyEvidence > keywordCount * 0.5 && earlyEvidence > 0) {
    lines.push({ text: "Большая часть данных пока на ранней стадии." });
  }

  if (singleScan > 0) {
    lines.push({
      text: `${formatCount(singleScan)} ключей пока имеют только один скан.`,
    });
  }

  return { tone: "informational", lines };
}

export function breakoutListSummary(
  items: KeywordPerformanceMetrics[],
  globalEligible: number | null | undefined,
): KeywordListSummary {
  if (globalEligible === 0) {
    return {
      tone: "neutral",
      lines: [
        {
          text: "Сейчас нет видео, подходящих для глобального breakout-рейтинга.",
          emphasis: true,
        },
      ],
    };
  }

  const withRate = items.filter((r) => r.top_decile_breakout_rate != null).length;
  return {
    tone: "informational",
    lines: [
      {
        text: `${formatCount(items.length)} ключей в выборке; ${formatCount(withRate)} с рассчитанной долей top-decile.`,
        emphasis: true,
      },
    ],
  };
}

export function outcomesListSummary(items: KeywordPerformanceMetrics[]): KeywordListSummary {
  const observed = items.reduce((s, r) => s + (r.observed_72h_video_count ?? 0), 0);
  const missing = items.reduce((s, r) => s + (r.missing_72h_video_count ?? 0), 0);

  if (observed === 0) {
    return {
      tone: "neutral",
      lines: [{ text: "Валидных 72 ч исходов в выборке пока нет.", emphasis: true }],
    };
  }

  const lines: SummaryLine[] = [
    {
      text: `Зафиксировано ${formatCount(observed)} валидных 72 ч наблюдений по ключам в выборке.`,
      emphasis: true,
    },
  ];

  if (missing > 0) {
    lines.push({
      text: `${formatCount(missing)} наблюдений без подходящего снимка на горизонте — это не сбой keyword.`,
    });
  }

  return { tone: "informational", lines };
}
