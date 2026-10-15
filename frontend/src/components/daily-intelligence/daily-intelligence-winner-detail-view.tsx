"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ErrorState, LoadingState, PageShell } from "@/components/design-system";
import { buttonVariants } from "@/components/ui/button";
import {
  getDailyIntelligenceReport,
  getDailyIntelligenceWinner,
  getDailyIntelligenceWinnerOutcomeFollowUp,
  listDailyIntelligenceVideoAppearances,
} from "@/lib/api";
import {
  formatChannelRelativeBlock,
  formatDiscoveryProvenance,
  formatWinnerMetrics,
} from "@/lib/daily-intelligence-evidence-format";
import type { DailyIntelligenceWinnerOutcomeFollowUp } from "@/lib/daily-intelligence-outcome-types";
import { dailyIntelligenceDayHref } from "@/lib/daily-intelligence-routes";
import type {
  DailyIntelligenceReportSummary,
  DailyIntelligenceVideoAppearanceItem,
  DailyIntelligenceWinnerDetail,
} from "@/lib/daily-intelligence-types";

import { DailyIntelligenceWinnerAttentionBlock } from "./daily-intelligence-winner-attention-block";
import { DailyIntelligenceWinnerHero } from "./daily-intelligence-winner-hero";
import { DailyIntelligenceWinnerObservationTimeline } from "./daily-intelligence-winner-observation-timeline";
import { DailyIntelligenceWinnerOutcomeStory } from "./daily-intelligence-winner-outcome-story";
import { DailyIntelligenceWinnerTechnicalEvidence } from "./daily-intelligence-winner-technical-evidence";

const APPEARANCE_PAGE_SIZE = 10;

export function DailyIntelligenceWinnerDetailView({
  reportDate,
  videoId,
}: {
  reportDate: string;
  videoId: string;
}) {
  const [loadState, setLoadState] = useState<"loading" | "error" | "ready">("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [report, setReport] = useState<DailyIntelligenceReportSummary | null>(null);
  const [winner, setWinner] = useState<DailyIntelligenceWinnerDetail | null>(null);

  const [appearances, setAppearances] = useState<DailyIntelligenceVideoAppearanceItem[]>([]);
  const [appearanceTotal, setAppearanceTotal] = useState(0);
  const [appearanceOffset, setAppearanceOffset] = useState(0);
  const [appearancesLoading, setAppearancesLoading] = useState(false);
  const [appearancesError, setAppearancesError] = useState<string | null>(null);

  const [followUp, setFollowUp] = useState<DailyIntelligenceWinnerOutcomeFollowUp | null>(null);
  const [followUpLoading, setFollowUpLoading] = useState(false);
  const [followUpError, setFollowUpError] = useState<string | null>(null);

  const loadCore = useCallback(async () => {
    setLoadState("loading");
    setFollowUp(null);
    setFollowUpError(null);
    try {
      const [reportData, winnerData] = await Promise.all([
        getDailyIntelligenceReport(reportDate),
        getDailyIntelligenceWinner(reportDate, videoId),
      ]);
      setReport(reportData);
      setWinner(winnerData);
      setLoadState("ready");
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : "Не удалось загрузить видео",
      );
      setLoadState("error");
    }
  }, [reportDate, videoId]);

  const loadAppearances = useCallback(
    async (offset: number) => {
      setAppearancesLoading(true);
      setAppearancesError(null);
      try {
        const data = await listDailyIntelligenceVideoAppearances(videoId, {
          limit: APPEARANCE_PAGE_SIZE,
          offset,
        });
        setAppearances(data.items);
        setAppearanceTotal(data.total);
        setAppearanceOffset(offset);
      } catch (error) {
        setAppearancesError(
          error instanceof Error ? error.message : "Ошибка загрузки истории",
        );
      } finally {
        setAppearancesLoading(false);
      }
    },
    [videoId],
  );

  const loadFollowUp = useCallback(async () => {
    setFollowUpLoading(true);
    setFollowUpError(null);
    try {
      const data = await getDailyIntelligenceWinnerOutcomeFollowUp(reportDate, videoId);
      setFollowUp(data);
    } catch (error) {
      setFollowUp(null);
      setFollowUpError(error instanceof Error ? error.message : "Ошибка follow-up");
    } finally {
      setFollowUpLoading(false);
    }
  }, [reportDate, videoId]);

  useEffect(() => {
    void loadCore();
  }, [loadCore]);

  useEffect(() => {
    if (loadState === "ready") {
      void loadAppearances(0);
      void loadFollowUp();
    }
  }, [loadState, loadAppearances, loadFollowUp]);

  const metrics = useMemo(
    () => formatWinnerMetrics(winner?.evidence ?? {}),
    [winner?.evidence],
  );
  const channelRelative = useMemo(
    () => formatChannelRelativeBlock(winner?.evidence?.channel_relative_signal),
    [winner?.evidence],
  );
  const provenance = useMemo(
    () => formatDiscoveryProvenance(winner?.discovery_provenance ?? {}),
    [winner?.discovery_provenance],
  );

  const unknowns = useMemo(() => {
    const ev = winner?.evidence ?? {};
    const missing: string[] = [];
    if (ev.views == null) missing.push("просмотры на момент публикации");
    if (ev.vph == null) missing.push("VPH");
    if (ev.subscribers == null) missing.push("подписчики канала");
    if (!channelRelative.hasData) missing.push("сигнал относительно канала");
    if (
      metrics.delayedOutcomeState === "Нет данных" &&
      metrics.delayedOutcomeGrowth === "Нет данных"
    ) {
      missing.push("72h outcome (не сохранён или не применим)");
    }
    if (provenance.summary.startsWith("Нет") || provenance.summary.includes("недоступен")) {
      missing.push("discovery provenance");
    }
    return missing;
  }, [winner?.evidence, channelRelative.hasData, metrics, provenance.summary]);

  if (loadState === "loading") {
    return (
      <PageShell>
        <LoadingState title="Загрузка карточки видео…" />
      </PageShell>
    );
  }

  if (loadState === "error" || !winner) {
    return (
      <PageShell>
        <ErrorState
          title="Видео не найдено"
          description={errorMessage}
          onRetry={() => void loadCore()}
        />
        <Link href={dailyIntelligenceDayHref(reportDate)} className={buttonVariants({ variant: "outline" })}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          К архиву за {reportDate}
        </Link>
      </PageShell>
    );
  }

  return (
    <PageShell>
      <div className="mb-4 max-w-4xl">
        <Link
          href={dailyIntelligenceDayHref(reportDate)}
          className={buttonVariants({ variant: "ghost", size: "sm" })}
        >
          <ArrowLeft className="mr-2 h-4 w-4" />
          Архив за {reportDate}
        </Link>
      </div>

      <div className="mx-auto max-w-4xl space-y-8 pb-10">
        <DailyIntelligenceWinnerHero
          reportDate={reportDate}
          report={report}
          winner={winner}
          videoId={videoId}
        />

        <DailyIntelligenceWinnerAttentionBlock metrics={metrics} editionRank={winner.rank} />

        <DailyIntelligenceWinnerOutcomeStory
          followUp={followUp}
          loading={followUpLoading}
          error={followUpError}
          onRetry={() => void loadFollowUp()}
        />

        <DailyIntelligenceWinnerObservationTimeline
          reportDate={reportDate}
          editionRank={winner.rank}
          appearances={appearances}
          appearanceTotal={appearanceTotal}
          appearanceOffset={appearanceOffset}
          appearancesLoading={appearancesLoading}
          appearancesError={appearancesError}
          followUp={followUp}
          onPageChange={(o) => void loadAppearances(o)}
          onRetry={() => void loadAppearances(appearanceOffset)}
        />

        <DailyIntelligenceWinnerTechnicalEvidence
          winner={winner}
          metrics={metrics}
          unknowns={unknowns}
          followUp={followUp}
          followUpLoading={followUpLoading}
          followUpError={followUpError}
          onFollowUpRetry={() => void loadFollowUp()}
        />
      </div>
    </PageShell>
  );
}
