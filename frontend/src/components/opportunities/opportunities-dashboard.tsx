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
          lead="Три типа сигналов Radar: ранние видео, динамика канала и повторяющиеся форматы. Данные из сохранённого снимка Attention."
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
          lead="Три типа сигналов Radar: ранние видео, динамика канала и повторяющиеся форматы."
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
          lead="Три типа сигналов Radar: ранние видео, динамика канала и повторяющиеся форматы."
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

  return (
    <PageShell>
      <PageHeader
        icon={<Flame className="h-6 w-6 text-primary" />}
        title="Возможности"
        lead="Три независимых блока без общего рейтинга: Video Winners (ранний сигнал по видео), Channel Momentum (сравнение канала с самим собой), Pattern Families (похожие форматы на разных каналах)."
      />

      <div className={cn(surfaces.section, "space-y-3 p-4")} data-testid="snapshot-meta">
        <p className="text-sm font-medium">{snapshotFreshnessLabel(summary.computed_at)}</p>
        <p className="text-sm text-muted-foreground">
          {windowHoursLabel(summary.window_hours)} · {candidateCountLabel(summary.candidate_video_count)}
        </p>
        <p className="text-xs text-muted-foreground">
          Снимок: {formatDateTimeLocal(summary.computed_at)} ({summary.timezone_name})
          {summary.run_id ? ` · ${summary.run_id}` : ""} · source={dataSource}
        </p>
        <p className="text-xs text-muted-foreground">
          Окно 72&nbsp;ч для delayed outcome — накопление наблюдений после discovery, а не задержка показа ранних
          Winners. VPH в таблице — средняя с публикации по последнему snapshot; ускорение между snapshots показывается
          только при acceleration_state=accelerating (≥3 точек VPH).
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3" data-testid="summary-cards">
        <a href="#video-winners" className={cn(surfaces.sectionMuted, "p-4 hover:border-primary/40")}>
          <Metric
            label="Видео набирают обороты"
            value={summary.winner_count}
            helper="Video Winners в снимке"
            testId="metric-winners"
          />
        </a>
        <a href="#channel-momentum" className={cn(surfaces.sectionMuted, "p-4 hover:border-primary/40")}>
          <Metric
            label="Растущие каналы"
            value={summary.channel_momentum_count}
            helper="Channel Momentum"
            testId="metric-channels"
          />
        </a>
        <a href="#pattern-families" className={cn(surfaces.sectionMuted, "p-4 hover:border-primary/40")}>
          <Metric
            label="Повторяющиеся форматы"
            value={families.length || summary.pattern_count}
            helper="Pattern Families"
            testId="metric-patterns"
          />
        </a>
      </div>

      <SectionPanel
        title="Видео набирают обороты"
        description="Отдельные Video Winners — ранний сигнал по одному ролику, не доказательство роста всего канала. Поиск, сортировка и ссылки на YouTube — в таблице ниже."
      >
        <div id="video-winners" className="space-y-2">
          <p className="text-xs text-muted-foreground">
            Подтверждённый рост views за 72&nbsp;ч после discovery (delayed outcome): {confirmed} из {videos.length} в
            текущем топе — только где есть hit и snapshot в tolerance-окне.
          </p>
          <WinnersTable videos={videos} />
        </div>
      </SectionPanel>

      <SectionPanel
        title="Растущие каналы"
        description="Channel Momentum: ≥2 recent и ≥2 previous с confirmed regular и snapshots ~24h от публикации; минимум два recent каждый ≥1.5× median previous на том же горизонте. Breakout / keyword 72h / подписчики — только контекст."
      >
        <div id="channel-momentum">
          <RisingChannelsSection channels={channels} winnerLookup={videos} />
        </div>
      </SectionPanel>

      <SectionPanel
        title="Повторяющиеся форматы"
        description="Pattern Families группируют похожие title/keyword/topic на разных каналах. Совпадение тем или фраз само по себе не доказывает успешность — смотрите breakout_eligible_count и исходные patterns."
      >
        <div id="pattern-families">
          {families.length === 0 ? (
            <p className="text-sm text-muted-foreground" data-testid="patterns-empty">
              В текущем снимке семейств паттернов нет.
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
    </PageShell>
  );
}
