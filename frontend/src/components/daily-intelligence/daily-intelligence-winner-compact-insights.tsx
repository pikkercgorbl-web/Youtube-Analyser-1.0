"use client";

import { buildDiWinnerInsightBlocks } from "@/lib/daily-intelligence-presentation";
import type { DailyIntelligenceReportSummary, DailyIntelligenceWinnerDetail } from "@/lib/daily-intelligence-types";
import { WinnerInsightBlocks } from "@/components/opportunities/winner-insight-blocks";

export function DailyIntelligenceWinnerCompactInsights({
  report,
  winner,
  hasOutcomeFollowUp,
}: {
  report: DailyIntelligenceReportSummary | null;
  winner: DailyIntelligenceWinnerDetail;
  hasOutcomeFollowUp: boolean;
}) {
  const blocks = buildDiWinnerInsightBlocks({
    report,
    evidence: winner.evidence ?? {},
    editionRank: winner.rank,
    discoveryProvenanceAvailable: winner.discovery_provenance_available,
    hasOutcomeFollowUp,
  });
  return <WinnerInsightBlocks blocks={blocks} />;
}
