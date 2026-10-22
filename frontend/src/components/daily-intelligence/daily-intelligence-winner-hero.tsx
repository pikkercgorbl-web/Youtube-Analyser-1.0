"use client";

import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import type { DailyIntelligenceReportSummary, DailyIntelligenceWinnerDetail } from "@/lib/daily-intelligence-types";

import { DailyIntelligenceSaveToResearchButton } from "./daily-intelligence-save-to-research-button";
import { DailyIntelligenceWinnerThumb } from "./daily-intelligence-winner-thumb";

export function DailyIntelligenceWinnerHero({
  reportDate,
  report,
  winner,
  videoId,
}: {
  reportDate: string;
  report: DailyIntelligenceReportSummary | null;
  winner: DailyIntelligenceWinnerDetail;
  videoId: string;
}) {
  return (
    <section
      className="rounded-2xl border border-border bg-gradient-to-b from-card/80 to-card/30 p-4 sm:p-6"
      data-testid="di-winner-hero"
    >
      <div className="flex flex-col gap-5 md:flex-row md:items-start">
        <DailyIntelligenceWinnerThumb
          videoId={winner.video_id}
          title={winner.title}
          href={winner.youtube_url}
          className="w-full max-w-[280px] shrink-0 mx-auto md:mx-0"
        />
        <div className="min-w-0 flex-1 space-y-3">
          <h1 className="text-xl sm:text-2xl font-semibold leading-snug break-words">{winner.title}</h1>
          {winner.channel_title ? (
            <p className="text-sm text-muted-foreground break-words">{winner.channel_title}</p>
          ) : null}
          <dl className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <div>
              <dt className="text-xs text-muted-foreground">День подборки (UTC)</dt>
              <dd className="font-medium tabular-nums">{reportDate}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Место в подборке</dt>
              <dd className="font-medium tabular-nums">#{winner.rank}</dd>
            </div>
            {report?.source_computed_at ? (
              <div className="max-w-xs">
                <dt className="text-xs text-muted-foreground">Публикация Attention</dt>
                <dd className="text-xs text-muted-foreground tabular-nums">
                  {new Date(report.source_computed_at).toLocaleString("ru-RU", {
                    day: "numeric",
                    month: "short",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </dd>
              </div>
            ) : null}
          </dl>
          {winner.is_repeat_in_prior_reports ? (
            <p className="text-xs text-amber-200/90 max-w-prose">
              Видео уже попадало в архивные подборки раньше выбранного дня.
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2 pt-1">
            <a
              href={winner.youtube_url}
              target="_blank"
              rel="noopener noreferrer"
              className={buttonVariants({ variant: "default", size: "sm" })}
            >
              Открыть на YouTube
            </a>
            <DailyIntelligenceSaveToResearchButton kind="video" reportDate={reportDate} videoId={videoId} />
          </div>
          <p className="text-xs text-muted-foreground max-w-prose pt-1">
            Снимок из архива Daily Intelligence — данные не обновляются из live Attention.
          </p>
        </div>
      </div>
    </section>
  );
}
