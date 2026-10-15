"use client";

import Link from "next/link";
import { ArrowLeft, CalendarDays } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ErrorState,
  LoadingState,
  Metric,
  MetricGroup,
  PageHeader,
  PageShell,
  SectionPanel,
} from "@/components/design-system";
import { buttonVariants } from "@/components/ui/button";
import { YoutubeThumb } from "@/components/opportunities/youtube-thumb";
import { getDailyIntelligenceFamily, getDailyIntelligenceReport } from "@/lib/api";
import { patternActivity } from "@/lib/attention-format";
import {
  FAMILY_QUALITY_FLAG_EXPLANATIONS,
  FROZEN_EVIDENCE_SOURCE,
  familyKindLabel,
  youtubeLinksForVideoIds,
} from "@/lib/daily-intelligence-evidence-format";
import { dailyIntelligenceStatusHint } from "@/lib/daily-intelligence-labels";
import { dailyIntelligenceDayHref } from "@/lib/daily-intelligence-routes";
import type {
  DailyIntelligenceFamilyDetail,
  DailyIntelligenceReportSummary,
} from "@/lib/daily-intelligence-types";
import { formatDateTimeLocal } from "@/lib/monitoring-format";

import { DailyIntelligenceFrozenJson } from "./daily-intelligence-frozen-json";
import { DailyIntelligenceSaveToResearchButton } from "./daily-intelligence-save-to-research-button";
import { DailyIntelligenceStatusBadge } from "./daily-intelligence-status-badge";

function isKeywordHeavy(flags: string[], familyKind: string): boolean {
  return (
    ["keyword", "topic", "keyword_provenance", "video_topic"].includes(familyKind) ||
    flags.includes("broad_keyword_group") ||
    flags.includes("keyword_only")
  );
}

export function DailyIntelligenceFamilyDetailView({
  reportDate,
  familyKey,
}: {
  reportDate: string;
  familyKey: string;
}) {
  const [loadState, setLoadState] = useState<"loading" | "error" | "ready">("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [report, setReport] = useState<DailyIntelligenceReportSummary | null>(null);
  const [family, setFamily] = useState<DailyIntelligenceFamilyDetail | null>(null);

  const load = useCallback(async () => {
    setLoadState("loading");
    try {
      const [reportData, familyData] = await Promise.all([
        getDailyIntelligenceReport(reportDate),
        getDailyIntelligenceFamily(reportDate, familyKey),
      ]);
      setReport(reportData);
      setFamily(familyData);
      setLoadState("ready");
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : "Не удалось загрузить family",
      );
      setLoadState("error");
    }
  }, [reportDate, familyKey]);

  useEffect(() => {
    void load();
  }, [load]);

  const evidence = useMemo(() => family?.evidence ?? {}, [family?.evidence]);
  const qualityFlags = (evidence.quality_flags as string[] | undefined) ?? [];
  const supportSources = (evidence.support_sources as string[] | undefined) ?? [];
  const groupingReasons = (evidence.grouping_reasons as string[] | undefined) ?? [];
  const memberLabels = (evidence.member_labels as string[] | undefined) ?? [];
  const memberKeys = (evidence.member_pattern_keys as string[] | undefined) ?? [];
  const videoIds = (evidence.video_ids as string[] | undefined) ?? [];
  const keywordIds = (evidence.keyword_ids as number[] | undefined) ?? [];
  const familyKind = String(evidence.family_kind ?? "");

  const activity = useMemo(
    () =>
      patternActivity({
        videos_last_24h: evidence.videos_last_24h as number,
        videos_previous_24h: evidence.videos_previous_24h as number,
        videos_previous_48_24h: evidence.videos_previous_48_24h as number,
      } as Parameters<typeof patternActivity>[0]),
    [
      evidence.videos_last_24h,
      evidence.videos_previous_24h,
      evidence.videos_previous_48_24h,
    ],
  );

  const videoLinks = useMemo(
    () => youtubeLinksForVideoIds((evidence.video_ids as string[] | undefined)?.slice(0, 12) ?? []),
    [evidence.video_ids],
  );

  if (loadState === "loading") {
    return (
      <PageShell>
        <LoadingState title="Загрузка исторической family…" />
      </PageShell>
    );
  }

  if (loadState === "error" || !family) {
    return (
      <PageShell>
        <ErrorState
          title="Family не найдена"
          description={errorMessage}
          onRetry={() => void load()}
        />
        <Link href={dailyIntelligenceDayHref(reportDate)} className={buttonVariants({ variant: "outline" })}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          К архиву за {reportDate}
        </Link>
      </PageShell>
    );
  }

  const keywordHeavy = isKeywordHeavy(qualityFlags, familyKind);
  const statusHint = report ? dailyIntelligenceStatusHint(report.status) : null;

  return (
    <PageShell>
      <div className="mb-4">
        <Link
          href={dailyIntelligenceDayHref(reportDate)}
          className={buttonVariants({ variant: "ghost", size: "sm" })}
        >
          <ArrowLeft className="mr-2 h-4 w-4" />
          UTC-день {reportDate}
        </Link>
      </div>

      <PageHeader
        icon={<CalendarDays className="h-7 w-7 text-primary" />}
        title={family.label}
        lead={
          keywordHeavy
            ? "Историческая подборка по теме/ключу. Совпадение не доказывает тренд."
            : "Историческая группа по сходству заголовков. Счётчики — снимок, не прогноз успеха."
        }
      />

      <SectionPanel title="Identity">
        <div className="space-y-3">
          <Metric label="Rank (daily edition)" value={`#${family.rank}`} />
          <p className="text-xs font-mono text-muted-foreground break-all" data-testid="di-family-key">
            {family.family_key}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-muted-foreground">UTC-день:</span>
            <span className="text-sm font-medium tabular-nums">{reportDate}</span>
            {report ? <DailyIntelligenceStatusBadge status={report.status} /> : null}
          </div>
          {statusHint ? (
            <p className="text-xs text-muted-foreground max-w-prose">{statusHint}</p>
          ) : null}
          <MetricGroup>
            <Metric
              label="Видео (снимок)"
              value={family.video_count ?? "Нет данных"}
              helper="Не доказательство монетизации"
            />
            <Metric label="Каналы (снимок)" value={family.channel_count ?? "Нет данных"} />
            <Metric label="Тип группировки" value={familyKindLabel(familyKind)} />
          </MetricGroup>
          {family.is_repeat_in_prior_reports ? (
            <p className="text-xs text-amber-200/90">Повтор в более ранних отчётах архива</p>
          ) : null}
          <DailyIntelligenceSaveToResearchButton
            kind="family"
            reportDate={reportDate}
            familyKey={familyKey}
          />
        </div>
      </SectionPanel>

      <SectionPanel title="Historical Evidence" description={FROZEN_EVIDENCE_SOURCE}>
        {qualityFlags.length > 0 ? (
          <div className="space-y-3" data-testid="di-family-quality-flags">
            <p className="text-sm font-medium">Quality flags</p>
            {qualityFlags.map((flag) => {
              const expl = FAMILY_QUALITY_FLAG_EXPLANATIONS[flag];
              return (
                <div key={flag} className="rounded-lg border border-border/60 px-3 py-2">
                  <p className="text-sm font-mono">{flag}</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {expl?.body ?? "Флаг из frozen payload без расшифровки в UI."}
                  </p>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Quality flags: Нет данных</p>
        )}

        {supportSources.length > 0 ? (
          <div className="mt-4">
            <p className="text-sm font-medium">Support sources</p>
            <ul className="mt-2 list-disc pl-5 text-sm text-muted-foreground">
              {supportSources.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {groupingReasons.length > 0 ? (
          <div className="mt-4">
            <p className="text-sm font-medium">Grouping reasons</p>
            <ul className="mt-2 list-disc pl-5 text-sm text-muted-foreground space-y-1">
              {groupingReasons.map((r) => (
                <li key={r} className="break-words">
                  {r}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {memberLabels.length > 0 ? (
          <div className="mt-4">
            <p className="text-sm font-medium">Member patterns</p>
            <ul className="mt-2 space-y-1 text-sm">
              {memberLabels.map((label, i) => (
                <li key={`${memberKeys[i] ?? i}-${label}`} className="break-words text-muted-foreground">
                  {label}
                  {memberKeys[i] ? (
                    <span className="block font-mono text-xs break-all">{memberKeys[i]}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {keywordIds.length > 0 ? (
          <p className="mt-4 text-sm text-muted-foreground">
            Keyword IDs (frozen): {keywordIds.join(", ")}
          </p>
        ) : null}

        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          <Metric
            label="Breakout eligible (в группе)"
            value={
              evidence.breakout_eligible_count != null
                ? String(evidence.breakout_eligible_count)
                : "Нет данных"
            }
            helper="Допуск к анализу, не число успешных роликов"
          />
          <Metric
            label="Активность (24h)"
            value={activity.available ? activity.label : "Недостаточно истории"}
          />
        </div>

        {evidence.first_seen_at || evidence.latest_seen_at ? (
          <p className="mt-3 text-xs text-muted-foreground">
            {evidence.first_seen_at
              ? `first_seen: ${formatDateTimeLocal(String(evidence.first_seen_at))}`
              : null}
            {evidence.latest_seen_at
              ? ` · latest_seen: ${formatDateTimeLocal(String(evidence.latest_seen_at))}`
              : null}
          </p>
        ) : null}

        {videoLinks.length > 0 ? (
          <div className="mt-4">
            <p className="text-sm font-medium">Representative videos (frozen IDs)</p>
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
              {videoLinks.map(({ id, url }, index) => (
                <a
                  key={id}
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`YouTube ${index + 1}`}
                >
                  <YoutubeThumb
                    videoId={id}
                    title={`Video ${index + 1}`}
                    className="aspect-video w-full rounded-lg"
                  />
                </a>
              ))}
            </div>
            {videoIds.length > videoLinks.length ? (
              <p className="mt-2 text-xs text-muted-foreground">
                Показаны первые {videoLinks.length} из {videoIds.length} ID в payload.
              </p>
            ) : null}
          </div>
        ) : (
          <p className="mt-4 text-sm text-muted-foreground">Representative videos: Нет данных</p>
        )}

        <DailyIntelligenceFrozenJson label="Raw frozen evidence (JSON)" payload={family.evidence} />
      </SectionPanel>
    </PageShell>
  );
}
