"use client";

import { SectionPanel } from "@/components/design-system";
import { HumanReasonsList } from "@/components/opportunities/signal-badges";
import { buildAttentionSummaryParagraph } from "@/lib/daily-intelligence-winner-research";
import type { WinnerMetricsFormatted } from "@/lib/daily-intelligence-winner-research";

import { DailyIntelligenceWinnerStatCard } from "./daily-intelligence-winner-stat-card";

export function DailyIntelligenceWinnerAttentionBlock({
  metrics,
  editionRank,
}: {
  metrics: WinnerMetricsFormatted;
  editionRank: number;
}) {
  const summary = buildAttentionSummaryParagraph(metrics, metrics.humanReasons);

  return (
    <SectionPanel
      title="Почему Radar выделил видео"
      description="Только то, что было сохранено в момент публикации Attention."
    >
      <p className="text-sm text-muted-foreground max-w-3xl leading-relaxed">{summary}</p>
      {metrics.humanReasons.length > 0 ? (
        <div className="mt-4">
          <HumanReasonsList reasons={metrics.humanReasons} />
        </div>
      ) : null}
      <div className="mt-5 grid gap-3 grid-cols-2 lg:grid-cols-4">
        <DailyIntelligenceWinnerStatCard label="Просмотры" value={metrics.views} />
        <DailyIntelligenceWinnerStatCard
          label="VPH"
          value={metrics.vph}
          hint="Просмотров в час на момент подборки"
        />
        <DailyIntelligenceWinnerStatCard label="Возраст видео" value={metrics.ageHours} />
        <DailyIntelligenceWinnerStatCard
          label="Место в подборке"
          value={`#${editionRank}`}
          hint="Итог daily edition за выбранный UTC-день"
        />
      </div>
    </SectionPanel>
  );
}
