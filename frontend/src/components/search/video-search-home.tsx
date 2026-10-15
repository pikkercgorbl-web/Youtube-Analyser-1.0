"use client";

import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import { SlidersHorizontal, X } from "lucide-react";

import { FiltersModal } from "@/components/search/FiltersModal";
import { ManualSearchVideoCard } from "@/components/search/ManualSearchVideoCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { EnrichedVideoModel } from "@/lib/types";
import {
  enrichSearchVideos,
  fetchManualSearchVideoContext,
  fetchSuggestions,
  getSavedVideo,
  searchVideos,
  type ManualSearchVideoContextItem,
} from "@/lib/api";
import {
  buildManualSearchApiPayload,
  clearLegacyManualSearchStorage,
  countManualSearchFilterGroups,
  DEFAULT_MANUAL_SEARCH_FILTERS,
  loadManualSearchFilters,
  manualSearchFilterChips,
  persistManualSearchFilters,
  type ManualSearchFilters,
} from "@/lib/manual-search-filters";
import {
  applyManualSearchLocalFilters,
  mergeEnrichedPreservingOrder,
} from "@/lib/manual-search-local-filter";
import { youtubeThumbnail } from "@/lib/utils";

const SUGGESTIONS_DEBOUNCE_MS = 300;

type SourceSavedContext = {
  savedId: number;
  videoId: string;
  title: string;
};

export function VideoSearchHome() {
  const searchParams = useSearchParams();
  const [query, setQuery] = useState("");
  const [rawResults, setRawResults] = useState<EnrichedVideoModel[]>([]);
  const [filters, setFilters] = useState<ManualSearchFilters>(DEFAULT_MANUAL_SEARCH_FILTERS);
  const [loading, setLoading] = useState(false);
  const [channelMetricsPending, setChannelMetricsPending] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [corpusContext, setCorpusContext] = useState<Record<string, ManualSearchVideoContextItem>>({});
  const [corpusContextError, setCorpusContextError] = useState<string | null>(null);
  const [sourceSaved, setSourceSaved] = useState<SourceSavedContext | null>(null);
  const suppressSuggestionsRef = useRef(false);
  const searchGenerationRef = useRef(0);

  const results = useMemo(
    () => applyManualSearchLocalFilters(rawResults, filters),
    [rawResults, filters],
  );
  const filterGroupCount = countManualSearchFilterGroups(filters);
  const filterChips = useMemo(() => manualSearchFilterChips(filters), [filters]);
  const showLocalFilterNotice = filterGroupCount > 0 && rawResults.length > 0;

  const hideSuggestions = useCallback(() => {
    suppressSuggestionsRef.current = true;
    setShowSuggestions(false);
    setSuggestions([]);
  }, []);

  useEffect(() => {
    clearLegacyManualSearchStorage();
    setFilters(loadManualSearchFilters());
  }, []);

  const handleVideoSearch = useCallback(
    async (searchQuery?: string) => {
      const trimmedQuery = (searchQuery ?? query).trim();
      if (!trimmedQuery) {
        return;
      }

      suppressSuggestionsRef.current = true;
      setQuery(trimmedQuery);
      setShowSuggestions(false);
      setSuggestions([]);
      setSearchError(null);
      setChannelMetricsPending(false);
      setLoading(true);
      const generation = ++searchGenerationRef.current;
      const payload = buildManualSearchApiPayload(trimmedQuery);

      try {
        const response = await searchVideos(payload, { phase: "full" });
        if (generation !== searchGenerationRef.current) {
          return;
        }
        const items = response.items;

        setRawResults(items);
        setHasSearched(true);
        setCorpusContext({});
        setCorpusContextError(null);
        setLoading(false);

        const ids = items.map((row) => row.video.video_id).filter(Boolean);
        if (ids.length > 0) {
          fetchManualSearchVideoContext(ids)
            .then((ctx) => {
              if (generation !== searchGenerationRef.current) {
                return;
              }
              const map: Record<string, ManualSearchVideoContextItem> = {};
              for (const row of ctx.items) {
                map[row.video_id] = row;
              }
              setCorpusContext(map);
              setCorpusContextError(null);
            })
            .catch((contextError) => {
              if (generation !== searchGenerationRef.current) {
                return;
              }
              setCorpusContext({});
              const message =
                contextError instanceof Error
                  ? contextError.message
                  : "Не удалось загрузить локальные статусы (база / сохранённое).";
              setCorpusContextError(message);
            });
        }

        if (response.needs_channel_enrichment && items.length > 0) {
          setChannelMetricsPending(true);
          try {
            const enriched = await enrichSearchVideos({ ...payload, items });
            if (generation !== searchGenerationRef.current) {
              return;
            }
            setRawResults((prev) => mergeEnrichedPreservingOrder(prev, enriched.items));
          } catch (enrichError) {
            if (generation !== searchGenerationRef.current) {
              return;
            }
            console.error("Subscriber enrichment failed", enrichError);
          } finally {
            if (generation === searchGenerationRef.current) {
              setChannelMetricsPending(false);
            }
          }
        }
      } catch (error) {
        if (generation !== searchGenerationRef.current) {
          return;
        }
        const errorMessage =
          error instanceof Error
            ? error.message
            : "Не удалось выполнить поиск. Проверьте, что бэкенд запущен.";
        console.error(errorMessage, error);
        setSearchError(errorMessage);
        setRawResults([]);
        setHasSearched(true);
        setCorpusContext({});
        setCorpusContextError(null);
      } finally {
        if (generation === searchGenerationRef.current) {
          setLoading(false);
        }
      }
    },
    [query],
  );

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    hideSuggestions();
    void handleVideoSearch();
  }

  useEffect(() => {
    const fromSaved = searchParams.get("from_saved") === "1";
    const initialQuery = searchParams.get("q")?.trim() ?? "";
    const sourceSavedIdRaw = searchParams.get("source_saved_id");
    const sourceVideoId = searchParams.get("source_video_id")?.trim() ?? "";

    if (initialQuery) {
      setQuery(initialQuery);
    }

    if (fromSaved && sourceSavedIdRaw) {
      const savedId = Number(sourceSavedIdRaw);
      if (Number.isFinite(savedId) && savedId > 0) {
        getSavedVideo(savedId)
          .then((detail) => {
            setSourceSaved({
              savedId: detail.id,
              videoId: detail.video_id,
              title: (() => {
                const identity = detail.frozen_snapshot?.identity as Record<string, unknown> | undefined;
                return identity?.title ? String(identity.title) : detail.video_id;
              })(),
            });
          })
          .catch(() => {
            if (sourceVideoId && initialQuery) {
              setSourceSaved({
                savedId,
                videoId: sourceVideoId,
                title: initialQuery,
              });
            } else {
              setSourceSaved(null);
            }
          });
      }
      return;
    }

    if (initialQuery && !fromSaved) {
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
        if (suppressSuggestionsRef.current) {
          suppressSuggestionsRef.current = false;
          setShowSuggestions(false);
          return;
        }
        setShowSuggestions(data.length > 0);
      } catch {
        setSuggestions([]);
        setShowSuggestions(false);
      }
    }, SUGGESTIONS_DEBOUNCE_MS);

    return () => window.clearTimeout(timer);
  }, [query]);

  function selectSuggestion(suggestion: string) {
    suppressSuggestionsRef.current = true;
    setQuery(suggestion);
    setShowSuggestions(false);
    setSuggestions([]);
    void handleVideoSearch(suggestion);
  }

  function applyFilters(next: ManualSearchFilters) {
    setFilters(next);
    persistManualSearchFilters(next);
  }

  function clearFilterChip(clear: (f: ManualSearchFilters) => ManualSearchFilters) {
    const next = clear(filters);
    applyFilters(next);
  }

  function resetAllFilters() {
    applyFilters(DEFAULT_MANUAL_SEARCH_FILTERS);
  }

  function handleSaved(videoId: string, savedId: number) {
    setCorpusContext((prev) => ({
      ...prev,
      [videoId]: {
        video_id: videoId,
        in_corpus: true,
        saved_video_id: savedId,
        snapshot_count: prev[videoId]?.snapshot_count ?? 0,
        latest_snapshot_at: prev[videoId]?.latest_snapshot_at ?? null,
      },
    }));
  }

  return (
    <div className="min-h-0 bg-background px-3 py-6 text-foreground sm:px-4 sm:py-10">
      <FiltersModal
        open={filtersOpen}
        filters={filters}
        onClose={() => setFiltersOpen(false)}
        onApply={applyFilters}
      />

      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
        <div className="space-y-2 text-center">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Поиск видео на YouTube</h1>
          <p className="text-sm text-muted-foreground">
            Быстрый InnerTube-поиск с сохранением видео и локальными фильтрами по выдаче
          </p>
        </div>

        {sourceSaved ? (
          <div className="mx-auto flex w-full max-w-3xl items-center gap-3 rounded-lg border border-border/60 bg-muted/30 p-3 text-sm">
            <Image
              src={youtubeThumbnail(sourceSaved.videoId)}
              alt=""
              width={80}
              height={45}
              unoptimized
              className="h-12 w-20 shrink-0 rounded object-cover"
            />
            <div className="min-w-0 flex-1">
              <p className="text-xs text-muted-foreground">Исследуем на основе</p>
              <Link
                href={`/saved/videos/${sourceSaved.savedId}`}
                className="line-clamp-2 font-medium hover:text-primary"
              >
                {sourceSaved.title}
              </Link>
            </div>
          </div>
        ) : null}

        <div className="mx-auto flex w-full max-w-3xl flex-col gap-3">
          <form className="flex flex-col gap-3 sm:flex-row sm:items-stretch" onSubmit={handleSubmit}>
            <div className="relative flex-1">
              <Input
                type="text"
                placeholder="Введите запрос, например: python tutorial"
                value={query}
                onChange={(event) => {
                  const value = event.target.value;
                  suppressSuggestionsRef.current = false;
                  setQuery(value);
                  if (value.trim().length <= 1) {
                    setShowSuggestions(false);
                  }
                }}
                onFocus={() => {
                  if (!suppressSuggestionsRef.current && suggestions.length > 0) {
                    setShowSuggestions(true);
                  }
                }}
                onBlur={() => {
                  setShowSuggestions(false);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    hideSuggestions();
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

            <Button type="submit" className="w-full sm:min-w-28 sm:w-auto" disabled={loading || !query.trim()}>
              Найти
            </Button>

            <Button
              type="button"
              variant="outline"
              className="w-full sm:w-auto"
              disabled={loading}
              onClick={() => setFiltersOpen(true)}
            >
              <SlidersHorizontal className="h-4 w-4" />
              Фильтры
              {filterGroupCount > 0 ? (
                <span className="ml-1 rounded-full bg-primary px-1.5 py-0.5 text-[10px] text-primary-foreground">
                  {filterGroupCount}
                </span>
              ) : null}
            </Button>
          </form>

          {filterChips.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2">
              {filterChips.map((chip) => (
                <button
                  key={chip.id}
                  type="button"
                  className="inline-flex items-center gap-1 rounded-full border border-border/60 bg-muted/40 px-2.5 py-1 text-xs transition-colors hover:bg-muted"
                  onClick={() => clearFilterChip(chip.clear)}
                >
                  {chip.label}
                  <X className="h-3 w-3 opacity-70" aria-hidden />
                </button>
              ))}
              <button
                type="button"
                className="text-xs text-primary underline-offset-2 hover:underline"
                onClick={resetAllFilters}
              >
                Сбросить всё
              </button>
            </div>
          ) : null}

          {showLocalFilterNotice ? (
            <p className="text-xs text-muted-foreground" role="status">
              Фильтры применены к загруженным результатам. Полнота по всему YouTube не гарантируется.
            </p>
          ) : null}
        </div>

        {searchError ? (
          <p className="text-center text-sm text-red-500" role="alert">
            {searchError}
          </p>
        ) : null}

        {!searchError && corpusContextError && rawResults.length > 0 ? (
          <p className="text-center text-sm text-amber-600 dark:text-amber-500" role="status">
            Результаты YouTube загружены. {corpusContextError}
          </p>
        ) : null}

        {loading ? (
          <p className="text-center text-sm text-muted-foreground">Ищем видео…</p>
        ) : null}

        {results.length > 0 ? (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {results.map((item) => (
              <ManualSearchVideoCard
                key={item.video.video_id}
                item={item}
                ctx={corpusContext[item.video.video_id]}
                metricsPending={channelMetricsPending}
                onSaved={(savedId) => handleSaved(item.video.video_id, savedId)}
              />
            ))}
          </div>
        ) : null}

        {!loading && !hasSearched ? (
          <p className="text-center text-sm text-muted-foreground">
            Введите запрос и нажмите «Найти», чтобы увидеть результаты.
          </p>
        ) : null}

        {!loading && hasSearched && rawResults.length === 0 && !searchError ? (
          <p className="text-center text-sm text-muted-foreground">Ничего не найдено.</p>
        ) : null}

        {!loading && hasSearched && rawResults.length > 0 && results.length === 0 && !searchError ? (
          <p className="text-center text-sm text-muted-foreground">
            Нет видео, подходящих под выбранные фильтры. Измените фильтры или сбросьте их.
          </p>
        ) : null}
      </div>
    </div>
  );
}
