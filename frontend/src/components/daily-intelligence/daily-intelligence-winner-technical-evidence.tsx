"use client";

import { Disclosure, Metric, MetricGroup, SectionPanel } from "@/components/design-system";
import { AttentionSignalBadges } from "@/components/opportunities/signal-badges";
import {
  FROZEN_EVIDENCE_SOURCE,
  formatChannelRelativeBlock,
  formatDiscoveryProvenance,
} from "@/lib/daily-intelligence-evidence-format";
import type { DailyIntelligenceWinnerOutcomeFollowUp } from "@/lib/daily-intelligence-outcome-types";
import type { DailyIntelligenceWinnerDetail } from "@/lib/daily-intelligence-types";
import type { WinnerMetricsFormatted } from "@/lib/daily-intelligence-winner-research";

import { DailyIntelligenceHistoricalFollowUpPanel } from "./daily-intelligence-historical-followup-panel";
import { DailyIntelligenceFrozenJson } from "./daily-intelligence-frozen-json";

export function DailyIntelligenceWinnerTechnicalEvidence({
  winner,
  metrics,
  unknowns,
  followUp,
  followUpLoading,
  followUpError,
  onFollowUpRetry,
}: {
  winner: DailyIntelligenceWinnerDetail;
  metrics: WinnerMetricsFormatted;
  unknowns: string[];
  followUp: DailyIntelligenceWinnerOutcomeFollowUp | null;
  followUpLoading: boolean;
  followUpError: string | null;
  onFollowUpRetry?: () => void;
}) {
  const channelRelative = formatChannelRelativeBlock(winner.evidence?.channel_relative_signal);
  const provenance = formatDiscoveryProvenance(winner.discovery_provenance ?? {});

  return (
    <SectionPanel
      title="Технические доказательства"
      description="Для аудита и отладки. На решение «сохранить в исследование» можно не опираться."
    >
      <Disclosure summary="Provenance, flags и пробелы данных" defaultOpen={false}>
        <div className="space-y-4 max-w-3xl">
          <div>
            <p className="text-sm font-medium">Discovery provenance</p>
            <p className="mt-1 text-sm text-muted-foreground">{provenance.summary}</p>
            {provenance.details.length > 0 ? (
              <ul className="mt-2 list-disc pl-5 text-xs text-muted-foreground space-y-0.5">
                {provenance.details.map((line) => (
                  <li key={line} className="break-all">
                    {line}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
          <div>
            <p className="text-sm font-medium">Относительно канала</p>
            {channelRelative.hasData ? (
              <ul className="mt-2 list-disc pl-5 text-sm text-muted-foreground space-y-1">
                {channelRelative.lines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">Нет данных</p>
            )}
          </div>
          <div>
            <p className="text-sm font-medium mb-2">Диагностические flags (не выводы)</p>
            <AttentionSignalBadges
              reasonCodes={metrics.reasonCodes}
              accelerationState={winner.evidence.acceleration_state as string | undefined}
              delayedOutcomeState={winner.evidence.delayed_outcome_state as string | undefined}
              channelRelativeStatus={
                (winner.evidence.channel_relative_signal as { status?: string } | undefined)?.status
              }
              treatAsWinner
            />
          </div>
          <div>
            <p className="text-sm font-medium">Чего Radar не знал на момент публикации</p>
            {unknowns.length === 0 ? (
              <p className="mt-2 text-sm text-muted-foreground">
                По доступным полям явных пробелов не отмечено (не гарантия полноты).
              </p>
            ) : (
              <ul className="mt-2 list-disc pl-5 text-sm text-muted-foreground space-y-1">
                {unknowns.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            )}
          </div>
          <p className="text-xs font-mono text-muted-foreground break-all">video_id: {winner.video_id}</p>
        </div>
      </Disclosure>

      <Disclosure summary="Расширенные метрики frozen evidence" defaultOpen={false}>
        <p className="text-xs text-muted-foreground mb-3">{FROZEN_EVIDENCE_SOURCE}</p>
        <MetricGroup>
          <Metric label="Подписчики" value={metrics.subscribers} />
          <Metric label="Ускорение" value={metrics.acceleration} />
          <Metric label="Breakout rank" value={metrics.breakoutRank} />
          <Metric label="Delayed outcome (снимок)" value={metrics.delayedOutcomeState} />
          <Metric label="Delayed outcome growth" value={metrics.delayedOutcomeGrowth} />
        </MetricGroup>
        <DailyIntelligenceFrozenJson label="Raw frozen evidence (JSON)" payload={winner.evidence} />
      </Disclosure>

      <Disclosure summary="Historical Follow-up (полный технический блок)" defaultOpen={false}>
        <DailyIntelligenceHistoricalFollowUpPanel
          followUp={followUp}
          loading={followUpLoading}
          error={followUpError}
          onRetry={onFollowUpRetry}
          embedded
        />
      </Disclosure>
    </SectionPanel>
  );
}
