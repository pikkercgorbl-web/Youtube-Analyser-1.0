"use client";

import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, ExternalLink, LineChart } from "lucide-react";

import { ChannelSingleAgeComparison } from "@/components/mass-analysis/channel-single-age-comparison";
import { ChannelSingleFocusCompact } from "@/components/mass-analysis/channel-single-focus-compact";
import { SaveVideoButton } from "@/components/saved-research/save-video-button";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { StateMessage } from "@/components/ui/state-message";
import {
  compareChannelSingleFocus,
  enrichChannelSingle,
  fetchChannelSingleShelf,
  fetchChannelSingleShelfMore,
} from "@/lib/api";
import { buildChannelSingleAnalysisFromRefUrl, buildChannelSingleAnalysisUrl } from "@/lib/channel-single-analysis-url";
import {
  isCurrentGeneration,
  shouldRunFocusCompare,
} from "@/lib/channel-single-analysis-loading";
import {
  computeViewsRank,
  formatViewsRankCaption,
  mergePublicationsByVideoId,
  samplePeriodLabel,
  sortRegularPublications,
  type RegularSortMode,
} from "@/lib/channel-single-analysis-overview";
import {
  CHANNEL_SINGLE_COMPARE_BUTTON_LABEL,
  CHANNEL_SINGLE_COMPARE_HINT,
  CHANNEL_SINGLE_COMPARE_SELECTED_LABEL,
} from "@/lib/channel-single-analysis-copy";
import { formatViewsAndAgeLine } from "@/lib/manual-search-published-format";
import type {
  ChannelSingleAnalysisEnrichResponse,
  ChannelSingleAnalysisPublication,
  ChannelSingleAnalysisShelfResponse,
} from "@/lib/types";
import {
  cn,
  formatCompactNumber,
  formatDuration,
  youtubeThumbnail,
} from "@/lib/utils";

const SHELF_MAX = 100;

function displayStatsLine(pub: ChannelSingleAnalysisPublication): string | null {
  const publishedHint = pub.published_text || pub.published_at || undefined;
  return formatViewsAndAgeLine(pub.views_count, publishedHint);
}

function durationLabel(pub: ChannelSingleAnalysisPublication): string | null {
  if (pub.duration_text?.trim()) {
    return pub.duration_text.trim();
  }
  if (pub.duration_seconds != null && pub.duration_seconds > 0) {
    return formatDuration(pub.duration_seconds);
  }
  return null;
}

function PublicationCard({
  pub,
  isFocus,
  onCompare,
  showCompare,
}: {
  pub: ChannelSingleAnalysisPublication;
  isFocus: boolean;
  onCompare: () => void;
  showCompare: boolean;
}) {
  const thumb = pub.thumbnail_url || youtubeThumbnail(pub.video_id);
  const stats = displayStatsLine(pub);
  const duration = durationLabel(pub);

  return (
    <Card
      className={cn(
        "overflow-hidden border-border/60",
        isFocus && "ring-2 ring-primary/70",
      )}
    >
      <a href={pub.url} target="_blank" rel="noopener noreferrer" className="block">
        <div className="relative aspect-video bg-muted">
          <Image src={thumb} alt="" fill unoptimized className="object-cover" sizes="33vw" />
          {duration ? (
            <span className="absolute bottom-2 right-2 rounded bg-black/80 px-1.5 py-0.5 text-xs text-white">
              {duration}
            </span>
          ) : null}
        </div>
      </a>
      <CardContent className="space-y-2 p-3">
        <a
          href={pub.url}
          target="_blank"
          rel="noopener noreferrer"
          className="line-clamp-2 text-sm font-medium hover:text-primary"
        >
          {pub.title || pub.video_id}
        </a>
        {stats ? <p className="text-xs text-muted-foreground">{stats}</p> : null}
        {isFocus ? (
          <p
            className="text-xs font-medium text-primary"
            data-testid="publication-compare-selected"
          >
            {CHANNEL_SINGLE_COMPARE_SELECTED_LABEL}
          </p>
        ) : null}
        <div className="flex flex-col gap-2 pt-1 sm:flex-row">
          {showCompare && !isFocus ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="flex-1"
              onClick={onCompare}
            >
              {CHANNEL_SINGLE_COMPARE_BUTTON_LABEL}
            </Button>
          ) : null}
          <SaveVideoButton videoId={pub.video_id} fromManualSearch skipInitialCheck />
        </div>
      </CardContent>
    </Card>
  );
}

export function ChannelSingleAnalysisHome() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const channelIdParam = searchParams.get("channel_id")?.trim() ?? "";
  const channelRefParam = searchParams.get("channel_ref")?.trim() ?? "";
  const focusVideoId = searchParams.get("focus_video_id")?.trim() ?? "";

  const [refInput, setRefInput] = useState(channelRefParam);
  const [shelf, setShelf] = useState<ChannelSingleAnalysisShelfResponse | null>(null);
  const [feedPublications, setFeedPublications] = useState<ChannelSingleAnalysisPublication[]>([]);
  const [hasMoreShelf, setHasMoreShelf] = useState(false);
  const [shelfPaginationNote, setShelfPaginationNote] = useState("");
  const [enrich, setEnrich] = useState<ChannelSingleAnalysisEnrichResponse | null>(null);
  const [enrichedPublications, setEnrichedPublications] = useState<ChannelSingleAnalysisPublication[]>([]);
  const [regularSort, setRegularSort] = useState<RegularSortMode>("newest");
  const [shelfLoading, setShelfLoading] = useState(false);
  const [enrichLoading, setEnrichLoading] = useState(false);
  const [compareLoading, setCompareLoading] = useState(false);
  const [loadMoreLoading, setLoadMoreLoading] = useState(false);
  const [shelfError, setShelfError] = useState<string | null>(null);
  const [enrichError, setEnrichError] = useState<string | null>(null);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);

  const loadGenerationRef = useRef(0);
  const enrichGenerationRef = useRef(0);
  const loadMoreGenerationRef = useRef(0);
  const prevFocusRef = useRef(focusVideoId);

  const enrichedReady = enrichedPublications.length > 0;
  const comparisonBusy = enrichLoading || compareLoading;
  const feedLoadedCount = feedPublications.length;

  const publicationsForOverview = enrichedReady ? enrichedPublications : feedPublications;

  const publicationsForGrid = useMemo(() => {
    const sorted = sortRegularPublications(publicationsForOverview, regularSort);
    if (!focusVideoId) {
      return sorted;
    }
    return sorted.filter((p) => p.video_id !== focusVideoId);
  }, [publicationsForOverview, regularSort, focusVideoId]);

  const focusPublication = useMemo(() => {
    if (!focusVideoId) {
      return null;
    }
    if (enrich?.focus?.video_id === focusVideoId) {
      return enrich.focus;
    }
    return publicationsForOverview.find((p) => p.video_id === focusVideoId) ?? null;
  }, [enrich, focusVideoId, publicationsForOverview]);

  const viewsRankCaption = useMemo(() => {
    if (!focusVideoId) {
      return null;
    }
    return formatViewsRankCaption(computeViewsRank(focusVideoId, publicationsForOverview));
  }, [focusVideoId, publicationsForOverview]);

  const periodLabel = useMemo(
    () => samplePeriodLabel(publicationsForOverview),
    [publicationsForOverview],
  );

  const loadShelf = useCallback(async () => {
    if (!channelIdParam && !channelRefParam) {
      return;
    }
    const generation = ++loadGenerationRef.current;
    enrichGenerationRef.current += 1;
    setShelfLoading(true);
    setShelfError(null);
    setEnrich(null);
    setFeedPublications([]);
    setEnrichedPublications([]);
    setHasMoreShelf(false);
    setShelfPaginationNote("");
    setEnrichError(null);
    setLoadMoreError(null);
    prevFocusRef.current = focusVideoId;

    try {
      const data = await fetchChannelSingleShelf({
        channel_id: channelIdParam || undefined,
        channel_ref: channelIdParam ? undefined : channelRefParam,
      });
      if (!isCurrentGeneration(generation, loadGenerationRef.current)) {
        return;
      }
      setShelf(data);
      setFeedPublications(data.publications);
      setHasMoreShelf(data.feed_loaded_count < SHELF_MAX);
    } catch (err) {
      if (!isCurrentGeneration(generation, loadGenerationRef.current)) {
        return;
      }
      setShelf(null);
      setShelfError(err instanceof Error ? err.message : "Не удалось загрузить канал");
    } finally {
      if (isCurrentGeneration(generation, loadGenerationRef.current)) {
        setShelfLoading(false);
      }
    }
  }, [channelIdParam, channelRefParam, focusVideoId]);

  const runEnrichForFeed = useCallback(
    async (
      channelId: string,
      publications: ChannelSingleAnalysisPublication[],
      focus: string,
    ) => {
      const generation = ++enrichGenerationRef.current;
      setEnrichLoading(true);
      setCompareLoading(false);
      setEnrichError(null);

      try {
        const data = await enrichChannelSingle({
          channel_id: channelId,
          focus_video_id: focus || undefined,
          publications,
        });
        if (!isCurrentGeneration(generation, enrichGenerationRef.current)) {
          return;
        }
        setEnrichedPublications(data.publications);
        setEnrich(data);
        prevFocusRef.current = focus;
        if (data.enrichment_error) {
          setEnrichError(data.enrichment_error);
        }
      } catch (err) {
        if (!isCurrentGeneration(generation, enrichGenerationRef.current)) {
          return;
        }
        setEnrichError(err instanceof Error ? err.message : "Не удалось обогатить данные");
      } finally {
        if (isCurrentGeneration(generation, enrichGenerationRef.current)) {
          setEnrichLoading(false);
        }
      }
    },
    [],
  );

  const runFocusCompare = useCallback(
    async (
      channelId: string,
      focus: string,
      publications: ChannelSingleAnalysisPublication[],
    ) => {
      if (!focus) {
        setEnrich((prev) =>
          prev
            ? {
                ...prev,
                focus: null,
                comparison: {
                  ...prev.comparison,
                  status: "no_focus",
                  message: "Видео для сравнения не выбрано.",
                  multiplier: null,
                  age_peer_samples: [],
                },
              }
            : prev,
        );
        return;
      }

      const generation = ++enrichGenerationRef.current;
      setCompareLoading(true);
      setEnrichError(null);

      try {
        const data = await compareChannelSingleFocus({
          channel_id: channelId,
          focus_video_id: focus,
          publications,
        });
        if (!isCurrentGeneration(generation, enrichGenerationRef.current)) {
          return;
        }
        setEnrich((prev) => {
          if (!prev) {
            return prev;
          }
          return {
            ...prev,
            comparison: data.comparison,
            focus: data.focus ?? prev.focus,
            focus_loaded_separately: data.focus_loaded_separately,
          };
        });
        if (data.enrichment_error) {
          setEnrichError(data.enrichment_error);
        }
      } catch (err) {
        if (!isCurrentGeneration(generation, enrichGenerationRef.current)) {
          return;
        }
        setEnrichError(err instanceof Error ? err.message : "Не удалось пересчитать сравнение");
      } finally {
        if (isCurrentGeneration(generation, enrichGenerationRef.current)) {
          setCompareLoading(false);
          setEnrichLoading(false);
        }
      }
    },
    [],
  );

  const loadMore = useCallback(async () => {
    if (!shelf?.channel_id || loadMoreLoading) {
      return;
    }
    if (feedLoadedCount >= SHELF_MAX) {
      return;
    }
    const generation = ++loadMoreGenerationRef.current;
    setLoadMoreLoading(true);
    setLoadMoreError(null);

    try {
      const data = await fetchChannelSingleShelfMore({
        channel_id: shelf.channel_id,
        existing_video_ids: feedPublications.map((p) => p.video_id),
        max_total: SHELF_MAX,
      });
      if (!isCurrentGeneration(generation, loadMoreGenerationRef.current)) {
        return;
      }
      const merged = mergePublicationsByVideoId(feedPublications, data.new_publications);
      setFeedPublications(merged);
      setHasMoreShelf(data.has_more && merged.length < SHELF_MAX);
      setShelfPaginationNote(data.pagination_note);
      await runEnrichForFeed(shelf.channel_id, merged, focusVideoId);
    } catch (err) {
      if (!isCurrentGeneration(generation, loadMoreGenerationRef.current)) {
        return;
      }
      setLoadMoreError(err instanceof Error ? err.message : "Не удалось загрузить ещё");
    } finally {
      if (isCurrentGeneration(generation, loadMoreGenerationRef.current)) {
        setLoadMoreLoading(false);
      }
    }
  }, [
    shelf?.channel_id,
    loadMoreLoading,
    feedLoadedCount,
    feedPublications,
    focusVideoId,
    runEnrichForFeed,
  ]);

  useEffect(() => {
    void loadShelf();
  }, [loadShelf]);

  useEffect(() => {
    if (!shelf) {
      return;
    }
    const pubs =
      feedPublications.length > 0 ? feedPublications : shelf.publications;
    if (pubs.length === 0) {
      return;
    }
    void runEnrichForFeed(shelf.channel_id, pubs, focusVideoId);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- focus handled by compare effect; load-more enriches explicitly
  }, [shelf?.channel_id, shelf?.fetched_at]);

  useEffect(() => {
    if (!shelf?.channel_id || !enrichedReady) {
      return;
    }
    if (!shouldRunFocusCompare(prevFocusRef.current, focusVideoId, enrichedReady)) {
      return;
    }
    prevFocusRef.current = focusVideoId;
    void runFocusCompare(shelf.channel_id, focusVideoId, enrichedPublications);
  }, [
    focusVideoId,
    enrichedReady,
    shelf?.channel_id,
    enrichedPublications,
    runFocusCompare,
  ]);

  function setFocus(videoId: string) {
    if (!shelf?.channel_id) {
      return;
    }
    router.replace(
      buildChannelSingleAnalysisUrl({
        channelId: shelf.channel_id,
        focusVideoId: videoId,
      }),
    );
  }

  function submitRef() {
    const trimmed = refInput.trim();
    if (!trimmed) {
      return;
    }
    router.push(buildChannelSingleAnalysisFromRefUrl(trimmed));
  }

  const comparison = enrich?.comparison;
  const regularCount = enrich?.regular_confirmed_count ?? 0;
  const fetchedAt = shelf?.fetched_at
    ? new Date(shelf.fetched_at).toLocaleString("ru-RU")
    : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Link
          href="/mass-analysis"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-primary"
        >
          <ArrowLeft className="h-4 w-4" />
          Анализ конкурентов
        </Link>
      </div>

      <header className="space-y-2">
        <div className="flex items-center gap-2">
          <LineChart className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-bold tracking-tight">Анализ канала</h1>
        </div>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Публикации автора с YouTube и ориентировочное сравнение выбранного ролика с роликами близкого возраста.
        </p>
      </header>

      {!channelIdParam && !channelRefParam ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Канал</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 sm:flex-row">
            <Input
              placeholder="https://youtube.com/@handle или UC…"
              value={refInput}
              onChange={(e) => setRefInput(e.target.value)}
            />
            <Button type="button" onClick={submitRef} disabled={!refInput.trim()}>
              Открыть
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {shelfLoading ? (
        <p className="text-sm text-muted-foreground">Загружаем публикации канала…</p>
      ) : null}

      {shelfError ? (
        <StateMessage variant="error" title="Канал не загружен" description={shelfError} />
      ) : null}

      {shelf && !shelfError ? (
        <>
          <Card>
            <CardContent className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center">
              {shelf.channel_avatar_url ? (
                <Image
                  src={shelf.channel_avatar_url}
                  alt=""
                  width={64}
                  height={64}
                  unoptimized
                  className="h-16 w-16 rounded-full object-cover ring-1 ring-border/60"
                />
              ) : null}
              <div className="min-w-0 flex-1 space-y-1">
                <h2 className="truncate text-lg font-semibold">{shelf.channel_title}</h2>
                {shelf.subscribers_count != null && shelf.subscribers_count > 0 ? (
                  <p className="text-sm text-muted-foreground">
                    {formatCompactNumber(shelf.subscribers_count)} подписчиков
                  </p>
                ) : null}
                <p className="text-xs text-muted-foreground">
                  В выборке {feedLoadedCount} публикаций вкладки Videos
                  {periodLabel ? ` · период ${periodLabel}` : ""}
                  {enrichedReady ? ` · подтверждено ${regularCount} обычных видео` : ""}
                  {fetchedAt ? ` · ${fetchedAt}` : ""}
                </p>
                {enrich?.focus_loaded_separately ? (
                  <p className="text-xs text-muted-foreground">
                    Выбранное видео загружено отдельно и не входит в счётчик ленты.
                  </p>
                ) : null}
                <a
                  href={`https://www.youtube.com/channel/${shelf.channel_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                >
                  Канал на YouTube
                  <ExternalLink className="h-3 w-3" />
                </a>
              </div>
            </CardContent>
          </Card>

          <div className="space-y-4 lg:flex lg:items-start lg:gap-4">
            {focusVideoId && focusPublication ? (
              <div className="min-w-0 flex-1">
                <ChannelSingleFocusCompact
                  pub={focusPublication}
                  channelTitle={shelf.channel_title}
                  viewsRankCaption={viewsRankCaption}
                />
              </div>
            ) : null}
            <div className="min-w-0 flex-1 lg:max-w-md">
              <ChannelSingleAgeComparison
                comparison={comparison}
                busy={comparisonBusy}
                enrichError={enrichError}
                hasFocus={Boolean(focusVideoId && focusPublication)}
              />
            </div>
          </div>

          <section className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="space-y-1">
                <h3 className="text-base font-semibold">Обычные видео в выборке</h3>
                {!focusVideoId ? (
                  <p className="text-sm text-muted-foreground">{CHANNEL_SINGLE_COMPARE_HINT}</p>
                ) : null}
              </div>
              <div className="flex rounded-md border border-border/60 p-0.5 text-sm">
                <button
                  type="button"
                  className={cn(
                    "rounded px-3 py-1",
                    regularSort === "newest" && "bg-muted font-medium",
                  )}
                  onClick={() => setRegularSort("newest")}
                >
                  Новые
                </button>
                <button
                  type="button"
                  className={cn(
                    "rounded px-3 py-1",
                    regularSort === "most_views" && "bg-muted font-medium",
                  )}
                  onClick={() => setRegularSort("most_views")}
                >
                  Больше просмотров
                </button>
              </div>
            </div>

            {enrichLoading && !enrichedReady ? (
              <p className="text-sm text-muted-foreground">Уточняем метаданные…</p>
            ) : null}

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {publicationsForGrid.map((pub) => (
                <PublicationCard
                  key={pub.video_id}
                  pub={pub}
                  isFocus={pub.video_id === focusVideoId}
                  showCompare
                  onCompare={() => setFocus(pub.video_id)}
                />
              ))}
            </div>

            {publicationsForGrid.length === 0 && enrichedReady ? (
              <p className="text-sm text-muted-foreground">Нет подтверждённых обычных видео в выборке.</p>
            ) : null}
          </section>

          {hasMoreShelf && feedLoadedCount < SHELF_MAX ? (
            <div className="space-y-2">
              <Button
                type="button"
                variant="outline"
                disabled={loadMoreLoading || shelfLoading}
                onClick={() => void loadMore()}
              >
                {loadMoreLoading ? "Загружаем…" : "Загрузить ещё"}
              </Button>
              <p className="text-xs text-muted-foreground">
                До {SHELF_MAX} публикаций. Расширяет обзор канала; не гарантирует больше роликов близкого возраста.
                {shelfPaginationNote ? ` ${shelfPaginationNote}` : ""}
              </p>
              {loadMoreError ? (
                <p className="text-xs text-amber-600 dark:text-amber-500">{loadMoreError}</p>
              ) : null}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
