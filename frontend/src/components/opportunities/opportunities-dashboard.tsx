"use client";

import { useCallback, useEffect, useState } from "react";
import { Flame } from "lucide-react";

import {
  ErrorState,
  LoadingState,
  Metric,
  PageHeader,
  PageShell,
  SectionPanel,
  UnavailableState,
} from "@/components/design-system";
import { PatternFamilyCard } from "@/components/opportunities/pattern-family-card";
import { RisingChannelsSection } from "@/components/opportunities/rising-channels";
import { WinnerCard } from "@/components/opportunities/winner-card";
import { WinnersTable } from "@/components/opportunities/winners-table";
import {
  getAttentionChannels,
  getAttentionPatternFamilies,
  getAttentionSummary,
  getAttentionVideos,
} from "@/lib/api";
import {
  candidateCountLabel,
  confirmed72hCount,
  snapshotFreshnessLabel,
  windowHoursLabel,
} from "@/lib/attention-format";
import type {
  AttentionChannelMomentum,
  AttentionPatternFamily,
  AttentionSummary,
  AttentionVideoWinner,
} from "@/lib/attention-types";
import { surfaces } from "@/lib/design-system/layout";
import { formatDateTimeLocal } from "@/lib/monitoring-format";
import { cn } from "@/lib/utils";

const PREVIEW_COUNT = 8;

type FeedState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "unavailable" }
  | {
      status: "ready";
      summary: AttentionSummary;
      dataSource: string;
      videos: AttentionVideoWinner[];
      families: AttentionPatternFamily[];
      channels: AttentionChannelMomentum[];
    };

export function OpportunitiesDashboard() {
  const [state, setState] = useState<FeedState>({ status: "loading" });

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const [summaryRes, videosRes, familiesRes, channelsRes] = await Promise.all([
        getAttentionSummary(),
        getAttentionVideos({ limit: 50 }),
        getAttentionPatternFamilies({ limit: 100 }),
        getAttentionChannels({ limit: 50 }),
      ]);
      const source = summaryRes.data_source;
      if (source === "unavailable" || !summaryRes.summary) {
        setState({ status: "unavailable" });
        return;
      }
      setState({
        status: "ready",
        summary: summaryRes.summary,
        dataSource: source,
        videos: videosRes.items,
        families: familiesRes.items,
        channels: channelsRes.items,
      });
    } catch (error) {
      setState({
        status: "error",
        message: error instanceof Error ? error.message : "Не удалось загрузить снимок Attention.",
      });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (state.status === "loading") {
    return (
      <PageShell>
        <PageHeader
          icon={<Flame className="h-6 w-6 text-primary" />}
          title="Возможности"
          lead="Radar сжимает тысячи найденных видео до сигналов, которые стоит проверить вручную."
        />
        <LoadingState title="Загрузка снимка Attention…" />
      </PageShell>
    );
  }

  if (state.status === "error") {
    return (
      <PageShell>
        <PageHeader
          icon={<Flame className="h-6 w-6 text-primary" />}
          title="Возможности"
          lead="Radar сжимает тысячи найденных видео до сигналов, которые стоит проверить вручную."
        />
        <ErrorState title="Не удалось загрузить Attention snapshot" description={state.message} onRetry={load} />
      </PageShell>
    );
  }

  if (state.status === "unavailable") {
    return (
      <PageShell>
        <PageHeader
          icon={<Flame className="h-6 w-6 text-primary" />}
          title="Возможности"
          lead="Radar сжимает тысячи найденных видео до сигналов, которые стоит проверить вручную."
        />
        <UnavailableState
          title="Attention Engine ещё не рассчитан."
          description="Это не live-лента. Сначала нужно сохранить снимок."
        />
        <p className="text-xs text-muted-foreground" data-testid="refresh-hint">
          python scripts/refresh_attention_engine.py
        </p>
      </PageShell>
    );
  }

  const { summary, videos, families, channels, dataSource } = state;
  const confirmed = confirmed72hCount(videos);
  const preview = videos.slice(0, PREVIEW_COUNT);

  return (
    <PageShell>
      <PageHeader
        icon={<Flame className="h-6 w-6 text-primary" />}
        title="Возможности"
        lead="Radar сжимает тысячи найденных видео до сигналов, которые стоит проверить вручную."
      />

      <div className={cn(surfaces.section, "space-y-3 p-4")} data-testid="snapshot-meta">
        <p className="text-sm">{snapshotFreshnessLabel(summary.computed_at)}</p>
        <p className="text-sm text-muted-foreground">
          {windowHoursLabel(summary.window_hours)} · {candidateCountLabel(summary.candidate_video_count)}
        </p>
        <p className="text-xs text-muted-foreground">
          source={dataSource} · computed_at={formatDateTimeLocal(summary.computed_at)} ({summary.timezone_name})
          {summary.run_id ? ` · ${summary.run_id}` : ""}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="summary-cards">
        <a href="#winners" className={cn(surfaces.sectionMuted, "p-4 hover:border-primary/40")}>
          <Metric label="🔥 Winners" value={summary.winner_count} testId="metric-winners" />
        </a>
        <a href="#patterns" className={cn(surfaces.sectionMuted, "p-4 hover:border-primary/40")}>
          <Metric label="📈 Patterns" value={families.length || summary.pattern_count} testId="metric-patterns" />
        </a>
        <a href="#channels" className={cn(surfaces.sectionMuted, "p-4 hover:border-primary/40")}>
          <Metric label="🌱 Rising Channels" value={summary.channel_momentum_count} testId="metric-channels" />
        </a>
        <div className={cn(surfaces.sectionMuted, "p-4")}>
          <Metric
            label="✅ 72h confirmed"
            value={confirmed}
            helper="по видео текущего топа, delayed_outcome_state=confirmed"
            testId="metric-72h"
          />
        </div>
      </div>

      <SectionPanel title="🔥 Победители" description="Короткий превью топа, затем полная таблица снимка.">
        <div id="winners" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {preview.map((video) => (
            <WinnerCard key={video.video_id} video={video} />
          ))}
        </div>
      </SectionPanel>

      <SectionPanel title="Все видео сегодняшнего топа" description="Все сохранённые VideoWinners текущего снимка. Без live-пересчёта.">
        <WinnersTable videos={videos} />
      </SectionPanel>

      <SectionPanel
        title="📈 Паттерны"
        description="Семейства паттернов: каноническая группа поверх исходных Pattern. Исходные строки не удаляются."
      >
        <div id="patterns">
          {families.length === 0 ? (
            <p className="text-sm text-muted-foreground" data-testid="patterns-empty">
              В текущем снимке паттернов нет.
            </p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {families.map((family) => (
                <PatternFamilyCard key={family.family_key} family={family} runId={summary.run_id} />
              ))}
            </div>
          )}
        </div>
      </SectionPanel>

      <SectionPanel title="🌱 Растущие каналы" description="Сравнение недавнего окна канала с его собственным предыдущим периодом.">
        <div id="channels">
          <RisingChannelsSection channels={channels} />
        </div>
      </SectionPanel>
    </PageShell>
  );
}
