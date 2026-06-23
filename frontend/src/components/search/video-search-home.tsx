"use client";

import Image from "next/image";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import { SlidersHorizontal } from "lucide-react";

import { FiltersModal } from "@/components/search/FiltersModal";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import type { EnrichedVideoModel } from "@/lib/types";
import { fetchSuggestions, searchVideos } from "@/lib/api";
import {
  buildSearchPayload,
  DEFAULT_BASE_FILTERS,
  DEFAULT_SEARCH_FILTERS,
  DURATION_OPTIONS,
  SORT_OPTIONS,
  UPLOAD_DATE_OPTIONS,
  VIDEO_TYPE_OPTIONS,
  type BaseFilters,
  type DurationOption,
  type SearchFilters,
  type SortOption,
  type UploadDateOption,
  type VideoTypeOption,
} from "@/lib/search-filters";
import { cn, formatNumber, youtubeThumbnail, youtubeVideoUrl } from "@/lib/utils";

const SUGGESTIONS_DEBOUNCE_MS = 300;

function resolveThumbnailUrl(item: EnrichedVideoModel): string {
  return item.video.thumbnail_url || youtubeThumbnail(item.video.video_id);
}

function resolveChannelAvatarUrl(item: EnrichedVideoModel): string {
  return item.channel.channel_avatar_url || item.video.channel_avatar_url || "";
}

function isShortVideo(item: EnrichedVideoModel): boolean {
  const duration = item.video.duration_text?.trim();
  return Boolean(item.video.is_short) || !duration || duration === "0:00";
}

function resolveTitle(item: EnrichedVideoModel): string {
  return item.video.title?.trim() || "Без названия";
}

function resolveChannelTitle(item: EnrichedVideoModel): string {
  return item.video.channel_title?.trim() || "Неизвестный канал";
}

function countAdvancedFilters(filters: SearchFilters): number {
  let count = 0;
  if (filters.hide_shorts) count += 1;
  if (filters.hide_regular) count += 1;
  if (filters.hide_streams) count += 1;
  if (filters.hide_hieroglyphs) count += 1;
  if (filters.virality_only_above_one) count += 1;
  if (filters.virality_min !== null) count += 1;
  if (filters.virality_max !== null) count += 1;
  if (filters.views_min !== null) count += 1;
  if (filters.views_max !== null) count += 1;
  if (filters.plus_words.length > 0) count += 1;
  if (filters.minus_words.length > 0) count += 1;
  if (filters.hide_verified) count += 1;
  if (filters.hide_artist) count += 1;
  if (filters.hide_kids) count += 1;
  if (filters.subscribers_min !== null) count += 1;
  if (filters.subscribers_max !== null) count += 1;
  if (filters.channel_views_min !== null) count += 1;
  if (filters.channel_views_max !== null) count += 1;
  if (filters.channel_videos_min !== null) count += 1;
  if (filters.channel_videos_max !== null) count += 1;
  if (filters.channel_age_min !== null) count += 1;
  if (filters.channel_age_max !== null) count += 1;
  return count;
}

export function VideoSearchHome() {
  const searchParams = useSearchParams();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<EnrichedVideoModel[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [baseFilters, setBaseFilters] = useState<BaseFilters>(DEFAULT_BASE_FILTERS);
  const [advancedFilters, setAdvancedFilters] = useState<SearchFilters>(DEFAULT_SEARCH_FILTERS);
  const [searchError, setSearchError] = useState<string | null>(null);

  const handleVideoSearch = useCallback(
    async (
      searchQuery?: string,
      baseOverride?: BaseFilters,
      advancedOverride?: SearchFilters,
    ) => {
      const trimmedQuery = (searchQuery ?? query).trim();
      if (!trimmedQuery) {
        return;
      }

      const base = baseOverride ?? baseFilters;
      const advanced = advancedOverride ?? advancedFilters;

      setQuery(trimmedQuery);
      setShowSuggestions(false);
      setSuggestions([]);
      setSearchError(null);
      setLoading(true);

      try {
        const data = await searchVideos(buildSearchPayload(trimmedQuery, base, advanced));
        setResults(data);
        setHasSearched(true);
      } catch (error) {
        const errorMessage =
          error instanceof Error
            ? error.message
            : "Не удалось выполнить поиск. Проверьте, что бэкенд запущен.";
        console.error(errorMessage, error);
        setSearchError(errorMessage);
        setResults([]);
        setHasSearched(true);
      } finally {
        setLoading(false);
      }
    },
    [query, baseFilters, advancedFilters],
  );

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void handleVideoSearch();
  }

  useEffect(() => {
    const initialQuery = searchParams.get("q")?.trim();
    if (initialQuery) {
      setQuery(initialQuery);
      void handleVideoSearch(initialQuery);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once for URL deep link
  }, []);

  useEffect(() => {
    const trimmedQuery = query.trim();

    if (trimmedQuery.length <= 1) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }

    const timer = window.setTimeout(async () => {
      try {
        const data = await fetchSuggestions(trimmedQuery);
        setSuggestions(data);
        setShowSuggestions(data.length > 0);
      } catch {
        setSuggestions([]);
        setShowSuggestions(false);
      }
    }, SUGGESTIONS_DEBOUNCE_MS);

    return () => window.clearTimeout(timer);
  }, [query]);

  function selectSuggestion(suggestion: string) {
    void handleVideoSearch(suggestion);
  }

  function updateBaseFilters(patch: Partial<BaseFilters>) {
    setBaseFilters((current) => ({ ...current, ...patch }));
  }

  function handleApplyAdvancedFilters(filters: SearchFilters) {
    setAdvancedFilters(filters);
    if (query.trim()) {
      void handleVideoSearch(query, baseFilters, filters);
    }
  }

  const advancedFilterCount = countAdvancedFilters(advancedFilters);

  return (
    <main className="min-h-screen bg-background px-4 py-10 text-foreground">
      <FiltersModal
        open={filtersOpen}
        filters={advancedFilters}
        onClose={() => setFiltersOpen(false)}
        onApply={handleApplyAdvancedFilters}
      />

      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
        <div className="space-y-2 text-center">
          <h1 className="text-3xl font-semibold tracking-tight">Поиск видео на YouTube</h1>
          <p className="text-sm text-muted-foreground">
            InnerTube-поиск с анализом каналов и коэффициентом виральности
          </p>
        </div>

        <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
          <form className="flex flex-col gap-3 sm:flex-row" onSubmit={handleSubmit}>
            <div className="relative flex-1">
              <Input
                type="text"
                placeholder="Введите запрос, например: python tutorial"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onFocus={() => {
                  if (suggestions.length > 0) {
                    setShowSuggestions(true);
                  }
                }}
                onBlur={() => {
                  window.setTimeout(() => setShowSuggestions(false), 150);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    setShowSuggestions(false);
                  }
                }}
                disabled={loading}
                autoComplete="off"
              />

              {showSuggestions && suggestions.length > 0 ? (
                <ul className="absolute left-0 right-0 top-[calc(100%+0.25rem)] z-20 max-h-72 overflow-y-auto rounded-md border border-border/60 bg-card py-1 shadow-lg">
                  {suggestions.map((suggestion) => (
                    <li key={suggestion}>
                      <button
                        type="button"
                        className="w-full px-3 py-2 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => selectSuggestion(suggestion)}
                      >
                        {suggestion}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>

            <Button type="submit" className="sm:min-w-28" disabled={loading || !query.trim()}>
              Найти
            </Button>
          </form>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Select
              aria-label="Тип видео"
              value={baseFilters.videoType}
              onChange={(event) =>
                updateBaseFilters({ videoType: event.target.value as VideoTypeOption })
              }
              disabled={loading}
            >
              {VIDEO_TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>

            <Select
              aria-label="Дата загрузки"
              value={baseFilters.uploadDate}
              onChange={(event) =>
                updateBaseFilters({ uploadDate: event.target.value as UploadDateOption })
              }
              disabled={loading}
            >
              {UPLOAD_DATE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>

            <Select
              aria-label="Длительность"
              value={baseFilters.duration}
              onChange={(event) =>
                updateBaseFilters({ duration: event.target.value as DurationOption })
              }
              disabled={loading}
            >
              {DURATION_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>

            <Select
              aria-label="Сортировка"
              value={baseFilters.sortBy}
              onChange={(event) =>
                updateBaseFilters({ sortBy: event.target.value as SortOption })
              }
              disabled={loading}
            >
              {SORT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </div>

          {!loading && hasSearched && results.length > 0 ? (
            <div className="flex justify-end">
              <Button type="button" variant="outline" onClick={() => setFiltersOpen(true)}>
                <SlidersHorizontal className="h-4 w-4" />
                Расширенные фильтры
                {advancedFilterCount > 0 ? (
                  <span className="ml-1 rounded-full bg-primary px-1.5 py-0.5 text-[10px] text-primary-foreground">
                    {advancedFilterCount}
                  </span>
                ) : null}
              </Button>
            </div>
          ) : null}
        </div>

        {searchError ? (
          <p className="text-center text-sm text-red-500" role="alert">
            {searchError}
          </p>
        ) : null}

        {loading ? (
          <p className="text-center text-sm text-muted-foreground">
            Ищем видео и анализируем каналы...
          </p>
        ) : null}

        {results.length > 0 ? (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {results.map((item) => {
              const thumbnailUrl = resolveThumbnailUrl(item);
              const channelAvatarUrl = resolveChannelAvatarUrl(item);
              const title = resolveTitle(item);
              const channelTitle = resolveChannelTitle(item);
              const isShort = isShortVideo(item);
              const durationText = item.video.duration_text?.trim();
              const viewsCount = item.video.views_count ?? 0;
              const subscribersCount = item.channel.subscribers_count ?? 0;
              const virality = item.virality_coefficient ?? 0;

              return (
                <Card
                  key={item.video.video_id}
                  className="overflow-hidden border-border/60 transition-shadow hover:shadow-lg hover:shadow-primary/5"
                >
                  <a
                    href={youtubeVideoUrl(item.video.video_id)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="group block"
                  >
                    <div className="relative aspect-video overflow-hidden bg-muted">
                      <Image
                        src={thumbnailUrl}
                        alt={title}
                        fill
                        unoptimized
                        className="object-cover transition-transform duration-300 group-hover:scale-105"
                        sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw"
                      />
                      {isShort ? (
                        <span className="absolute bottom-2 right-2 rounded bg-rose-600/90 px-1.5 py-0.5 text-xs font-medium text-white">
                          Shorts
                        </span>
                      ) : durationText ? (
                        <span className="absolute bottom-2 right-2 rounded bg-black/80 px-1.5 py-0.5 text-xs font-medium text-white">
                          {durationText}
                        </span>
                      ) : null}
                    </div>
                  </a>

                  <CardContent className="space-y-3 p-4">
                    <a
                      href={youtubeVideoUrl(item.video.video_id)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="line-clamp-2 text-base font-semibold leading-snug hover:text-primary"
                    >
                      {title}
                    </a>

                    <div className="flex items-center gap-2">
                      {channelAvatarUrl ? (
                        <Image
                          src={channelAvatarUrl}
                          alt={channelTitle}
                          width={28}
                          height={28}
                          unoptimized
                          className="h-7 w-7 shrink-0 rounded-full object-cover ring-1 ring-border/60"
                        />
                      ) : (
                        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold uppercase text-muted-foreground ring-1 ring-border/60">
                          {channelTitle.slice(0, 1) || "?"}
                        </div>
                      )}
                      <p className="truncate text-sm text-muted-foreground">{channelTitle}</p>
                    </div>

                    <div className="space-y-1.5 text-sm">
                      <p>
                        <span className="text-muted-foreground">Просмотры: </span>
                        {formatNumber(viewsCount)}
                      </p>
                      <p>
                        <span className="text-muted-foreground">Подписчики: </span>
                        {subscribersCount > 0 ? formatNumber(subscribersCount) : "—"}
                      </p>
                      <p className={cn("font-bold text-emerald-400")}>
                        Коэффициент виральности: {virality.toFixed(2)}
                      </p>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        ) : null}

        {!loading && !hasSearched ? (
          <p className="text-center text-sm text-muted-foreground">
            Введите запрос и нажмите «Найти», чтобы увидеть результаты.
          </p>
        ) : null}

        {!loading && hasSearched && results.length === 0 && !searchError ? (
          <p className="text-center text-sm text-muted-foreground">Ничего не найдено.</p>
        ) : null}
      </div>
    </main>
  );
}
