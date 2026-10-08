"use client";

import { useCallback, useEffect, useState } from "react";
import { Flame } from "lucide-react";

import {
  ErrorState,
  LoadingState,
  PageHeader,
  PageShell,
  SectionPanel,
  UnavailableState,
} from "@/components/design-system";
import {
  PatternFamilyCard,
  isTopicCollection,
} from "@/components/opportunities/pattern-family-card";
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
  const [section, setSection] = useState<"videos" | "channels" | "families">(
    "videos",
  );
  const [state, setState] = useState<FeedState>({ status: "loading" });

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const [summaryRes, videosRes, familiesRes, channelsRes] =
        await Promise.all([
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
        message:
          error instanceof Error
            ? error.message
            : "Не удалось загрузить снимок Attention.",
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
          lead="Видео, каналы и темы, которые стоит изучить."
        />
        <LoadingState title="Ищем сохранённые находки…" />
      </PageShell>
    );
  }

  if (state.status === "error") {
    return (
      <PageShell>
        <PageHeader
          icon={<Flame className="h-6 w-6 text-primary" />}
          title="Возможности"
          lead="Видео, каналы и темы, которые стоит изучить."
        />
        <ErrorState
          title="Не удалось загрузить находки"
          description={state.message}
          onRetry={load}
        />
      </PageShell>
    );
  }

  if (state.status === "unavailable") {
    return (
      <PageShell>
        <PageHeader
          icon={<Flame className="h-6 w-6 text-primary" />}
          title="Возможности"
          lead="Видео, каналы и темы, которые стоит изучить."
        />
        <UnavailableState
          title="Подборка ещё не готова."
          description="После первого расчёта Radar здесь появятся находки. Состояние сбора можно проверить в разделе «Состояние системы»."
        />
        <p className="text-xs text-muted-foreground" data-testid="refresh-hint">
          python scripts/refresh_attention_engine.py
        </p>
      </PageShell>
    );
  }

  const { summary, videos, families, channels, dataSource } = state;
  const confirmed = confirmed72hCount(videos);

  const repeated = families.filter((family) => !isTopicCollection(family));
  const topics = families.filter(isTopicCollection);
  const stale =
    Date.now() - new Date(summary.computed_at).getTime() > 3 * 3600_000;
  return (
    <PageShell>
      <PageHeader
        icon={<Flame className="h-7 w-7 text-primary" />}
        title="Возможности"
        lead="Найдите следующий повод для разведки. От отдельного ролика — к повторяющемуся результату."
      />
      <div
        className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-border bg-card px-5 py-4"
        data-testid="snapshot-meta"
      >
        <div>
          <p
            className={cn(
              "text-sm font-medium",
              stale ? "text-amber-300" : "text-primary",
            )}
          >
            {snapshotFreshnessLabel(summary.computed_at)}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {windowHoursLabel(summary.window_hours)} ·{" "}
            {candidateCountLabel(summary.candidate_video_count)}
          </p>
        </div>
        <details className="max-w-xl text-sm text-muted-foreground">
          <summary>О данных</summary>
          <div className="mt-3 space-y-2">
            <p>
              Расчёт: {formatDateTimeLocal(summary.computed_at)} (местное
              время).{" "}
              {stale
                ? "Подборка давно не обновлялась. Проверьте состояние системы."
                : "Показана сохранённая подборка."}
            </p>
            <p className="break-all text-xs">
              {summary.run_id} · source={dataSource}
            </p>
            <p>
              Рост через 72 часа после обнаружения подтверждён у {confirmed} из{" "}
              {videos.length} видео. Ранние находки доступны до этого срока.
            </p>
          </div>
        </details>
      </div>
      <div
        className="grid grid-cols-3 gap-2 sm:gap-3"
        data-testid="summary-cards"
        aria-label="Тип находок"
      >
        {(
          [
            [
              "videos",
              "Видео для разведки",
              summary.winner_count,
              "Отдельные ранние сигналы",
              "metric-winners",
            ],
            [
              "channels",
              "Растущие каналы",
              summary.channel_momentum_count,
              "Повторяемый результат",
              "metric-channels",
            ],
            [
              "families",
              "Похожие находки",
              families.length,
              "Сходство заголовков и тем",
              "metric-patterns",
            ],
          ] as const
        ).map(([key, label, count, helper, testId]) => (
          <button
            key={key}
            type="button"
            aria-pressed={section === key}
            onClick={() => setSection(key)}
            className={cn(
              "rounded-2xl border p-3 sm:p-5 text-left transition-colors",
              section === key
                ? "neon-active border-primary/30"
                : "border-border bg-card hover:border-primary/30",
            )}
          >
            <span className="text-xs sm:text-sm text-muted-foreground">
              {label}
            </span>
            <span
              className="mt-2 block text-3xl font-semibold tabular-nums"
              data-testid={testId}
            >
              {count}
            </span>
            <span className="mt-2 hidden text-sm text-muted-foreground sm:block">
              {helper}
            </span>
          </button>
        ))}
      </div>
      <div hidden={section !== "videos"}>
        <SectionPanel
          title="Видео для разведки"
          description="Изучите сам ролик и соседние публикации канала. Один удачный результат ещё не доказывает повторяемость."
        >
          <div id="video-winners">
            <WinnersTable videos={videos} />
          </div>
        </SectionPanel>
      </div>
      <div hidden={section !== "channels"}>
        <SectionPanel
          title="Растущие каналы"
          description="Несколько недавних видео показывают улучшение относительно предыдущих роликов канала на одинаковом возрасте."
        >
          <div id="channel-momentum">
            <RisingChannelsSection channels={channels} winnerLookup={videos} />
          </div>
        </SectionPanel>
      </div>
      <div
        hidden={section !== "families"}
        className="space-y-8"
        id="pattern-families"
      >
        <SectionPanel
          title="Повторяющиеся находки"
          description="Сходство заголовков на разных каналах — повод сравнить видео, а не готовый рецепт успеха."
        >
          {repeated.length ? (
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              {repeated.map((family) => (
                <PatternFamilyCard
                  key={family.family_key}
                  family={family}
                  runId={summary.run_id}
                />
              ))}
            </div>
          ) : (
            <p
              className="rounded-2xl border border-dashed border-border p-6 text-muted-foreground"
              data-testid="patterns-empty"
            >
              Пока нет групп со сходством заголовков. Тематические подборки
              доступны ниже, если они есть в текущем расчёте.
            </p>
          )}
        </SectionPanel>
        {topics.length > 0 ? (
          <SectionPanel
            title="Подборки по теме"
            description="Видео объединены общим запросом или темой. Повторяемость производственного формата здесь не установлена."
          >
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              {topics.map((family) => (
                <PatternFamilyCard
                  key={family.family_key}
                  family={family}
                  runId={summary.run_id}
                />
              ))}
            </div>
          </SectionPanel>
        ) : null}
      </div>
    </PageShell>
  );
}
