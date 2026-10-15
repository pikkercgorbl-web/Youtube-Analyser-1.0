"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Flame } from "lucide-react";

import {
  ErrorState,
  LoadingState,
  PageHeader,
  PageShell,
  SectionPanel,
  UnavailableState,
} from "@/components/design-system";
import { PatternFamilyCard } from "@/components/opportunities/pattern-family-card";
import {
  isNeedsReviewFamily,
  isRepeatingIdeaFamily,
  isSearchCollectionFamily,
} from "@/lib/opportunity-family-presentation";
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
import type { RelatedFamilyRef } from "@/lib/saved-research-types";
import { formatDateTimeLocal } from "@/lib/monitoring-format";
import { cn } from "@/lib/utils";
import { parseWinnerVideoIdFromHash } from "@/lib/opportunity-family-presentation";

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
  const [focusWinnerVideoId, setFocusWinnerVideoId] = useState<string | null>(
    null,
  );
  const [state, setState] = useState<FeedState>({ status: "loading" });

  const focusWinnerFromLocation = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const videoId = parseWinnerVideoIdFromHash(window.location.hash);
    if (!videoId) {
      return;
    }
    setSection("videos");
    setFocusWinnerVideoId(null);
    window.requestAnimationFrame(() => setFocusWinnerVideoId(videoId));
  }, []);

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

  const [locationHash, setLocationHash] = useState("");

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const syncHash = () => setLocationHash(window.location.hash);
    syncHash();
    window.addEventListener("hashchange", syncHash);
    return () => window.removeEventListener("hashchange", syncHash);
  }, []);

  useEffect(() => {
    if (state.status !== "ready") {
      return;
    }
    focusWinnerFromLocation();
    window.addEventListener("hashchange", focusWinnerFromLocation);
    return () =>
      window.removeEventListener("hashchange", focusWinnerFromLocation);
  }, [state.status, locationHash, focusWinnerFromLocation]);

  const relatedFamiliesByVideoId = useMemo(() => {
    if (state.status !== "ready") {
      return {} as Record<string, RelatedFamilyRef[]>;
    }
    const map: Record<string, RelatedFamilyRef[]> = {};
    for (const family of state.families) {
      const ref = { family_key: family.family_key, label: family.label };
      for (const videoId of family.participating_video_ids) {
        map[videoId] = [...(map[videoId] ?? []), ref];
      }
    }
    for (const key of Object.keys(map)) {
      map[key].sort((a, b) => a.label.localeCompare(b.label, "ru"));
    }
    return map;
  }, [state]);

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

  const repeatingIdeas = families.filter(isRepeatingIdeaFamily);
  const needsReview = families.filter(isNeedsReviewFamily);
  const searchCollections = families.filter(isSearchCollectionFamily);
  const winnerTitleById = Object.fromEntries(
    videos.map((row) => [row.video_id, row.title]),
  );
  const stale =
    Date.now() - new Date(summary.computed_at).getTime() > 3 * 3600_000;
  return (
    <PageShell>
      <section className="radar-hero" aria-label="Обзор разведки">
        <div className="radar-orbit" aria-hidden="true" />
        <p className="mb-5 text-[11px] font-medium uppercase tracking-[0.24em] text-primary">NicheScope / Разведка YouTube</p>
        <div className="relative max-w-2xl">
          <PageHeader
            title="Возможности"
            lead="Замечайте сигналы. Изучайте видео. Находите свою следующую идею."
          />
        </div>
      </section>
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
              "Группы для исследования",
              families.length,
              "Подборки и сходства заголовков",
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
              "radar-panel rounded-2xl border p-3 sm:p-5 text-left transition-colors",
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
            <WinnersTable
              videos={videos}
              runId={summary.run_id}
              relatedFamiliesByVideoId={relatedFamiliesByVideoId}
              focusVideoId={focusWinnerVideoId}
              onFocusVideoHandled={() => setFocusWinnerVideoId(null)}
            />
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
        {repeatingIdeas.length > 0 ? (
          <SectionPanel
            title="Повторяющиеся идеи"
            description="Только группы, где узкий признак в названиях совпал минимум у двух видео с разных каналов и есть минимум два Winner с разных каналов."
          >
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              {repeatingIdeas.map((family) => (
                <PatternFamilyCard
                  key={family.family_key}
                  family={family}
                  runId={summary.run_id}
                  winnerTitlesById={winnerTitleById}
                />
              ))}
            </div>
          </SectionPanel>
        ) : (
          <p
            className="rounded-2xl border border-dashed border-border px-4 py-3 text-sm text-muted-foreground"
            data-testid="patterns-empty"
          >
            Повторяющих идей в этом снимке нет. Winners ({summary.winner_count})
            — во вкладке{" "}
            <button
              type="button"
              className="text-primary underline-offset-2 hover:underline"
              onClick={() => setSection("videos")}
            >
              «Видео для разведки»
            </button>
            ; подборки поиска — ниже.
          </p>
        )}
        {needsReview.length > 0 ? (
          <SectionPanel
            title="Требует проверки"
            description="Сходство заголовков видно по сохранённым evidence — сравните ролики вручную."
          >
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              {needsReview.map((family) => (
                <PatternFamilyCard
                  key={family.family_key}
                  family={family}
                  runId={summary.run_id}
                  winnerTitlesById={winnerTitleById}
                />
              ))}
            </div>
          </SectionPanel>
        ) : null}
        {searchCollections.length > 0 ? (
          <SectionPanel
            title="Подборки поиска"
            description="Видео объединены одним запросом или темой из метаданных. Это не подтверждённая возможность и не доказанный формат."
          >
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              {searchCollections.map((family) => (
                <PatternFamilyCard
                  key={family.family_key}
                  family={family}
                  runId={summary.run_id}
                  winnerTitlesById={winnerTitleById}
                />
              ))}
            </div>
          </SectionPanel>
        ) : null}
      </div>
    </PageShell>
  );
}
