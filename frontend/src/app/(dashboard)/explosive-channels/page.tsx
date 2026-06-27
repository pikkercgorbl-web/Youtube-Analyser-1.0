"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Flame, Loader2, Radar, RotateCcw, Sparkles, Square, Trash2 } from "lucide-react";

import { AiIdeasModal } from "@/components/explosive-channels/ai-ideas-modal";
import { ExplosiveChannelCard } from "@/components/explosive-channels/explosive-channel-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { StateMessage } from "@/components/ui/state-message";
import {
  clearExplosiveChannels,
  fetchExplosiveChannels,
  fetchRadarStats,
  fetchRadarStatus,
  fetchSuggestions,
  generateRadarIdeas,
  resetRadarQueue,
  stopRadarSearch,
  toggleRadar,
  updateRadarSettings,
} from "@/lib/api";
import { buildYouTubeSearchQuery } from "@/lib/build-search-query";
import { filterRuEnExplosiveChannels, sortExplosiveChannels } from "@/lib/explosive-channels";
import {
  RADAR_FILTER_STORAGE_KEYS,
  hasStoredUploadPeriod,
  readStoredNumber,
  readStoredSortBy,
  readStoredUploadPeriod,
  writeStoredNumber,
  writeStoredSortBy,
  writeStoredUploadPeriod,
} from "@/lib/radar-filter-storage";
import type {
  ExplosiveChannelItem,
  ExplosiveChannelSortOption,
  RadarStatsResponse,
  RadarStatusResponse,
  RadarUploadPeriod,
} from "@/lib/types";
import { cn, formatCompactNumber, formatNumber } from "@/lib/utils";

const SORT_OPTIONS: { value: ExplosiveChannelSortOption; label: string }[] = [
  { value: "viral_coefficient_desc", label: "По коэффициенту виральности (убывание)" },
  { value: "video_views_desc", label: "По просмотрам (убывание)" },
  { value: "vph_desc", label: "По VPH (убывание)" },
];

const DEFAULT_MIN_VIEWS = 50_000;
const DEFAULT_MIN_VIRAL_COEFF = 3.0;
const FETCH_DEBOUNCE_MS = 400;
const SUGGESTIONS_DEBOUNCE_MS = 300;
const RADAR_LIVE_UPDATE_MS = 10_000;

const UPLOAD_PERIOD_OPTIONS: { value: RadarUploadPeriod; label: string }[] = [
  { value: "all", label: "За всё время" },
  { value: "month", label: "До 1 месяца" },
  { value: "3_months", label: "До 3 месяцев" },
  { value: "6_months", label: "До 6 месяцев" },
  { value: "year", label: "До 1 года" },
];

export default function ExplosiveChannelsPage() {
  const [channels, setChannels] = useState<ExplosiveChannelItem[]>([]);
  const [sortBy, setSortBy] = useState<ExplosiveChannelSortOption>(() =>
    readStoredSortBy("viral_coefficient_desc"),
  );
  const [minViews, setMinViews] = useState(() =>
    readStoredNumber(RADAR_FILTER_STORAGE_KEYS.minViews, DEFAULT_MIN_VIEWS),
  );
  const [minViralCoeff, setMinViralCoeff] = useState(() =>
    readStoredNumber(RADAR_FILTER_STORAGE_KEYS.minViralCoeff, DEFAULT_MIN_VIRAL_COEFF),
  );
  const [initialLoading, setInitialLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isScanning, setIsScanning] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [resetNotice, setResetNotice] = useState<string | null>(null);
  const [clearError, setClearError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [radarStatus, setRadarStatus] = useState<RadarStatusResponse | null>(null);
  const [radarStatusLoading, setRadarStatusLoading] = useState(true);
  const [radarStats, setRadarStats] = useState<RadarStatsResponse | null>(null);
  const [radarStatsLoading, setRadarStatsLoading] = useState(true);
  const [radarStatsError, setRadarStatsError] = useState<string | null>(null);
  const [uploadPeriod, setUploadPeriod] = useState<RadarUploadPeriod>(() =>
    readStoredUploadPeriod("all"),
  );
  const [uploadPeriodError, setUploadPeriodError] = useState<string | null>(null);
  const [isLangFilterActive, setIsLangFilterActive] = useState(false);
  const [radarSearchQuery, setRadarSearchQuery] = useState("");
  const [radarSuggestions, setRadarSuggestions] = useState<string[]>([]);
  const [showRadarSuggestions, setShowRadarSuggestions] = useState(false);
  const [plusWordsInput, setPlusWordsInput] = useState("");
  const [minusWordsInput, setMinusWordsInput] = useState("");
  const [aiModalOpen, setAiModalOpen] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiIdeas, setAiIdeas] = useState<string[]>([]);
  const [isManualSearchActive, setIsManualSearchActive] = useState(false);
  const [isStoppingSearch, setIsStoppingSearch] = useState(false);
  const [excludeStreams, setExcludeStreams] = useState(false);
  const [excludeShorts, setExcludeShorts] = useState(false);
  const [excludeVideos, setExcludeVideos] = useState(false);

  useEffect(() => {
    const trimmedQuery = radarSearchQuery.trim();

    if (trimmedQuery.length <= 1) {
      setRadarSuggestions([]);
      setShowRadarSuggestions(false);
      return;
    }

    const timer = window.setTimeout(async () => {
      try {
        const data = await fetchSuggestions(trimmedQuery);
        setRadarSuggestions(data);
        setShowRadarSuggestions(data.length > 0);
      } catch {
        setRadarSuggestions([]);
        setShowRadarSuggestions(false);
      }
    }, SUGGESTIONS_DEBOUNCE_MS);

    return () => window.clearTimeout(timer);
  }, [radarSearchQuery]);

  useEffect(() => {
    writeStoredNumber(RADAR_FILTER_STORAGE_KEYS.minViews, minViews);
  }, [minViews]);

  useEffect(() => {
    writeStoredNumber(RADAR_FILTER_STORAGE_KEYS.minViralCoeff, minViralCoeff);
  }, [minViralCoeff]);

  useEffect(() => {
    writeStoredUploadPeriod(uploadPeriod);
  }, [uploadPeriod]);

  useEffect(() => {
    writeStoredSortBy(sortBy);
  }, [sortBy]);

  const loadRadarStatus = useCallback(async () => {
    try {
      const data = await fetchRadarStatus();
      setRadarStatus(data);
      if (!hasStoredUploadPeriod()) {
        setUploadPeriod(data.upload_period);
      }
    } catch {
      setRadarStatus(null);
    } finally {
      setRadarStatusLoading(false);
    }
  }, []);

  const loadRadarStats = useCallback(async () => {
    setRadarStatsError(null);

    try {
      const data = await fetchRadarStats();
      setRadarStats(data);
    } catch (err) {
      setRadarStatsError(err instanceof Error ? err.message : "Ошибка загрузки статистики радара");
    } finally {
      setRadarStatsLoading(false);
    }
  }, []);

  const loadChannels = useCallback(async (options?: { silent?: boolean }) => {
    const silent = options?.silent ?? false;
    if (!silent) {
      setIsRefreshing(true);
    }
    setError(null);

    try {
      const data = await fetchExplosiveChannels({
        min_views: minViews,
        min_viral_coeff: minViralCoeff,
      });
      setChannels(data);
    } catch (err) {
      if (!silent) {
        setError(err instanceof Error ? err.message : "Ошибка загрузки");
        setChannels([]);
      }
    } finally {
      if (!silent) {
        setIsRefreshing(false);
        setInitialLoading(false);
      }
    }
  }, [minViews, minViralCoeff]);

  useEffect(() => {
    void loadRadarStatus();
    void loadRadarStats();
  }, [loadRadarStatus, loadRadarStats]);

  useEffect(() => {
    const isSearchActive =
      (radarStatus?.is_running ?? false) || radarStatus?.worker_status === "running";

    if (!isSearchActive) {
      return;
    }

    const timer = window.setInterval(() => {
      void loadChannels({ silent: true });
      void loadRadarStatus();
    }, RADAR_LIVE_UPDATE_MS);

    return () => window.clearInterval(timer);
  }, [
    radarStatus?.is_running,
    radarStatus?.worker_status,
    loadChannels,
    loadRadarStatus,
  ]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadChannels();
    }, FETCH_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timer);
    };
  }, [loadChannels]);

  const sortedChannels = useMemo(
    () => sortExplosiveChannels(channels, sortBy),
    [channels, sortBy],
  );

  const visibleChannels = useMemo(() => {
    if (!isLangFilterActive) {
      return sortedChannels;
    }
    return filterRuEnExplosiveChannels(sortedChannels);
  }, [sortedChannels, isLangFilterActive]);

  const radarProgressPercent = useMemo(() => {
    if (!radarStats || radarStats.total_keywords <= 0) {
      return 0;
    }
    return Math.min(
      100,
      Math.round((radarStats.checked_today / radarStats.total_keywords) * 100),
    );
  }, [radarStats]);

  const isRadarRunning = radarStatus?.is_running ?? false;
  const workerStatus = radarStatus?.worker_status ?? "idle";
  const showStopSearchButton =
    isManualSearchActive && (isRadarRunning || workerStatus === "running");

  const handleToggleRadar = async () => {
    setIsScanning(true);
    setScanError(null);
    setShowRadarSuggestions(false);

    try {
      const manualQuery = !isRadarRunning
        ? buildYouTubeSearchQuery(radarSearchQuery, plusWordsInput, minusWordsInput)
        : undefined;
      const status = await toggleRadar(uploadPeriod, manualQuery || undefined, {
        exclude_streams: excludeStreams,
        exclude_shorts: excludeShorts,
        exclude_videos: excludeVideos,
      });
      setRadarStatus(status);
      setUploadPeriod(status.upload_period);
      if (manualQuery && status.is_running) {
        setIsManualSearchActive(true);
      }
      if (!status.is_running && status.worker_status !== "running") {
        setIsManualSearchActive(false);
      }
      if (status.is_running) {
        await Promise.all([loadRadarStats(), loadChannels({ silent: true })]);
      }
    } catch (err) {
      setScanError(err instanceof Error ? err.message : "Ошибка переключения радара");
    } finally {
      setIsScanning(false);
    }
  };

  const handleStopSearch = async () => {
    setIsStoppingSearch(true);
    setScanError(null);

    try {
      const status = await stopRadarSearch();
      setRadarStatus(status);
      setIsManualSearchActive(false);
      await loadChannels({ silent: true });
    } catch (err) {
      setScanError(err instanceof Error ? err.message : "Не удалось остановить поиск");
    } finally {
      setIsStoppingSearch(false);
    }
  };

  const handleUploadPeriodChange = async (value: RadarUploadPeriod) => {
    setUploadPeriod(value);
    setUploadPeriodError(null);

    try {
      const status = await updateRadarSettings(value);
      setRadarStatus(status);
      setUploadPeriod(status.upload_period);
    } catch (err) {
      setUploadPeriodError(
        err instanceof Error ? err.message : "Не удалось сохранить период загрузки",
      );
    }
  };

  const handleResetRadar = async () => {
    if (
      !window.confirm(
        "Сбросить очередь радара? Следующий цикл начнётся с первого ключевого слова в списке.",
      )
    ) {
      return;
    }

    setIsResetting(true);
    setResetNotice(null);
    setScanError(null);

    try {
      const response = await resetRadarQueue();
      setResetNotice(response.message);
      await loadRadarStats();
    } catch (err) {
      setScanError(err instanceof Error ? err.message : "Не удалось сбросить очередь радара");
    } finally {
      setIsResetting(false);
    }
  };

  const handleGenerateIdeas = async () => {
    const titles = visibleChannels
      .map((channel) => channel.representative_video_title.trim())
      .filter(Boolean);

    if (titles.length === 0) {
      setAiError("Нет названий видео для анализа");
      setAiIdeas([]);
      setAiModalOpen(true);
      return;
    }

    setAiModalOpen(true);
    setAiLoading(true);
    setAiError(null);
    setAiIdeas([]);

    try {
      const response = await generateRadarIdeas(titles);
      setAiIdeas(response.ideas);
    } catch (err) {
      setAiError(err instanceof Error ? err.message : "Не удалось сгенерировать идеи");
    } finally {
      setAiLoading(false);
    }
  };

  const handleClearChannels = async () => {
    if (
      !window.confirm(
        "Вы уверены, что хотите удалить все найденные каналы? Это действие необратимо.",
      )
    ) {
      return;
    }

    setIsClearing(true);
    setClearError(null);

    try {
      await clearExplosiveChannels();
      setChannels([]);
    } catch (err) {
      setClearError(err instanceof Error ? err.message : "Ошибка очистки базы");
    } finally {
      setIsClearing(false);
    }
  };

  return (
    <div className="space-y-6">
      <header className="space-y-4">
        <div>
          <div className="flex items-center gap-2">
            <Flame className="h-6 w-6 text-primary" />
            <h1 className="text-xl font-bold tracking-tight sm:text-2xl">Взрывные каналы</h1>
          </div>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
            Молодые каналы с виральными видео. Настройте пороги и включите радар вручную — он будет
            сканировать ключевые слова пакетами, пока вы его не выключите.
          </p>
        </div>

        <div className="flex flex-col gap-3 rounded-xl border border-border/60 bg-card/80 p-4 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
          <p className="text-sm text-muted-foreground">
            Всего каналов в базе:{" "}
            <span className="font-semibold tabular-nums text-foreground">{channels.length}</span>
          </p>

          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
            <div className="relative w-full sm:min-w-[220px] sm:flex-1">
              <Input
                type="text"
                placeholder="Введите слово или оставьте пустым"
                value={radarSearchQuery}
                onChange={(event) => {
                  const value = event.target.value;
                  setRadarSearchQuery(value);
                  setShowRadarSuggestions(value.trim().length > 0);
                }}
                onFocus={() => {
                  if (radarSearchQuery.trim().length > 0 && radarSuggestions.length > 0) {
                    setShowRadarSuggestions(true);
                  }
                }}
                onBlur={() => {
                  setShowRadarSuggestions(false);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    setShowRadarSuggestions(false);
                  }
                }}
                disabled={isScanning || isRadarRunning || radarStatusLoading}
                className="w-full"
                maxLength={256}
                autoComplete="off"
              />

              {showRadarSuggestions && radarSuggestions.length > 0 ? (
                <ul className="absolute left-0 right-0 top-[calc(100%+0.25rem)] z-50 max-h-72 overflow-y-auto rounded-md border border-border/60 bg-card py-1 shadow-lg">
                  {radarSuggestions.map((suggestion) => (
                    <li key={suggestion}>
                      <button
                        type="button"
                        className="w-full px-3 py-2 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => {
                          setRadarSearchQuery(suggestion);
                          setShowRadarSuggestions(false);
                        }}
                      >
                        {suggestion}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>

            <Input
              type="text"
              placeholder="Плюс-слова (через запятую)"
              value={plusWordsInput}
              onChange={(event) => setPlusWordsInput(event.target.value)}
              disabled={isScanning || isRadarRunning || radarStatusLoading}
              className="w-full sm:min-w-[220px] sm:flex-1"
              maxLength={256}
            />

            <Input
              type="text"
              placeholder="Минус-слова (через запятую)"
              value={minusWordsInput}
              onChange={(event) => setMinusWordsInput(event.target.value)}
              disabled={isScanning || isRadarRunning || radarStatusLoading}
              className="w-full sm:min-w-[220px] sm:flex-1"
              maxLength={256}
            />

            <Select
              label="Период загрузки видео"
              value={uploadPeriod}
              onChange={(event) =>
                void handleUploadPeriodChange(event.target.value as RadarUploadPeriod)
              }
              className="w-full sm:w-52"
              disabled={isScanning || radarStatusLoading}
            >
              {UPLOAD_PERIOD_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>

            {isRadarRunning ? (
              <div className="flex items-center gap-2 text-sm text-emerald-400">
                <span className="relative flex h-2.5 w-2.5 shrink-0">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
                </span>
                Радар сканирует...
              </div>
            ) : null}

            {showStopSearchButton ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="w-full shrink-0 border-rose-500/40 text-rose-300 hover:bg-rose-500/10 sm:w-auto"
                disabled={isStoppingSearch}
                onClick={() => void handleStopSearch()}
              >
                {isStoppingSearch ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Остановка...
                  </>
                ) : (
                  <>
                    <Square className="h-4 w-4 fill-current" />
                    Остановить поиск
                  </>
                )}
              </Button>
            ) : null}

            <Button
              type="button"
              size="sm"
              className={cn(
                "w-full shrink-0 sm:min-w-[180px] sm:w-auto",
                isRadarRunning
                  ? "bg-muted text-muted-foreground hover:bg-muted/80"
                  : "bg-indigo-600 text-white hover:bg-indigo-500",
              )}
              disabled={isScanning || isClearing || initialLoading || radarStatusLoading}
              onClick={() => void handleToggleRadar()}
            >
              {isScanning ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Переключение...
                </>
              ) : isRadarRunning ? (
                "⏹ Остановить радар"
              ) : (
                "▶ Запустить радар"
              )}
            </Button>

            <Button
              type="button"
              variant="outline"
              size="sm"
              className="w-full shrink-0 sm:w-auto"
              disabled={isResetting || isScanning || initialLoading || radarStatusLoading}
              onClick={() => void handleResetRadar()}
            >
              {isResetting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Сброс...
                </>
              ) : (
                <>
                  <RotateCcw className="h-4 w-4" />
                  Начать сначала
                </>
              )}
            </Button>

            <Button
              type="button"
              variant="destructive"
              size="sm"
              className="w-full shrink-0 sm:w-auto"
              disabled={isClearing || isScanning || initialLoading}
              onClick={() => void handleClearChannels()}
            >
              {isClearing ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Очистка...
                </>
              ) : (
                <>
                  <Trash2 className="h-4 w-4" />
                  Очистить базу
                </>
              )}
            </Button>
          </div>
          {uploadPeriodError ? (
            <p className="w-full text-xs text-rose-400">{uploadPeriodError}</p>
          ) : null}
          {resetNotice ? (
            <p className="w-full text-xs text-emerald-400">{resetNotice}</p>
          ) : null}
        </div>

        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <section className="w-full flex-1 rounded-xl border border-border/60 bg-card/80 p-4">
            <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex items-center gap-2">
                <Radar className="h-4 w-4 text-primary" />
                <h2 className="text-sm font-semibold">Настройка радара</h2>
                {isRefreshing && !isScanning ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                ) : null}
              </div>

              <div className="flex min-w-[220px] flex-col gap-2">
                <p className="text-xs text-muted-foreground">
                  {radarStatusLoading ? (
                    "Проверка статуса..."
                  ) : isRadarRunning ? (
                    "Радар включён"
                  ) : (
                    "Радар выключен"
                  )}
                </p>

                <div className="space-y-1.5">
                  <p className="text-xs text-muted-foreground">
                    {radarStatsLoading ? (
                      "Загрузка прогресса..."
                    ) : radarStats ? (
                      <>
                        Проверено за 24ч:{" "}
                        <span className="font-semibold tabular-nums text-foreground">
                          {formatNumber(radarStats.checked_today)}
                        </span>{" "}
                        /{" "}
                        <span className="font-semibold tabular-nums text-foreground">
                          {formatNumber(radarStats.total_keywords)}
                        </span>{" "}
                        слов
                      </>
                    ) : (
                      "Прогресс сканирования недоступен"
                    )}
                  </p>
                  {!radarStatsLoading && radarStats ? (
                    <Progress
                      value={radarProgressPercent}
                      indicatorClassName="bg-emerald-500"
                      className="max-w-xs"
                    />
                  ) : null}
                  {radarStatsError ? (
                    <p className="text-xs text-rose-400">{radarStatsError}</p>
                  ) : null}
                </div>
              </div>
            </div>

            {scanError ? (
              <p className="mb-4 text-sm text-rose-400">{scanError}</p>
            ) : null}

            {clearError ? (
              <p className="mb-4 text-sm text-rose-400">{clearError}</p>
            ) : null}

            <div className="grid gap-5 md:grid-cols-2">
              <div className="space-y-2">
                <label
                  htmlFor="min-views"
                  className="flex items-center justify-between text-sm font-medium text-muted-foreground"
                >
                  <span>Мин. просмотров на видео</span>
                  <span className="tabular-nums text-foreground">
                    {formatCompactNumber(minViews)}
                  </span>
                </label>
                <Input
                  id="min-views"
                  type="number"
                  min={0}
                  step={1000}
                  value={minViews}
                  onChange={(event) => {
                    const next = Number.parseInt(event.target.value, 10);
                    setMinViews(Number.isFinite(next) && next >= 0 ? next : 0);
                  }}
                />
              </div>

              <Slider
                label="Мин. коэффициент виральности"
                value={minViralCoeff}
                min={1}
                max={50}
                step={0.5}
                formatValue={(value) => `${value.toFixed(1)}×`}
                onChange={setMinViralCoeff}
              />
            </div>
          </section>

          <Select
            label="Сортировка"
            value={sortBy}
            onChange={(event) => setSortBy(event.target.value as ExplosiveChannelSortOption)}
            className="w-full xl:w-80"
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>

          <label className="flex w-full cursor-pointer items-center gap-3 rounded-xl border border-border/60 bg-card/80 px-4 py-3 xl:w-80">
            <input
              type="checkbox"
              checked={isLangFilterActive}
              onChange={(event) => setIsLangFilterActive(event.target.checked)}
              className="h-4 w-4 shrink-0 rounded border-border accent-primary"
            />
            <span className="text-sm leading-snug">Только RU/EN (Скрыть иероглифы)</span>
          </label>

          <div className="flex w-full flex-col gap-2 xl:w-80">
            <ContentFormatToggle
              label="Не искать трансляции"
              checked={excludeStreams}
              disabled={isScanning || isRadarRunning || radarStatusLoading}
              onChange={setExcludeStreams}
            />
            <ContentFormatToggle
              label="Не искать Shorts"
              checked={excludeShorts}
              disabled={isScanning || isRadarRunning || radarStatusLoading}
              onChange={setExcludeShorts}
            />
            <ContentFormatToggle
              label="Не искать обычные видео"
              checked={excludeVideos}
              disabled={isScanning || isRadarRunning || radarStatusLoading}
              onChange={setExcludeVideos}
            />
          </div>
        </div>
      </header>

      {initialLoading ? <ExplosiveChannelsSkeleton /> : null}

      {!initialLoading && error ? (
        <StateMessage variant="error" title="Не удалось загрузить каналы" description={error} />
      ) : null}

      {!initialLoading && !error && sortedChannels.length === 0 ? (
        <StateMessage
          title="Нет каналов по текущим фильтрам"
          description={`Попробуйте ослабить пороги радара или включите радар — каналы от ${formatNumber(minViews)} просмотров и коэффициентом от ${minViralCoeff.toFixed(1)}× появятся здесь.`}
        />
      ) : null}

      {!initialLoading && !error && sortedChannels.length > 0 && visibleChannels.length === 0 ? (
        <StateMessage
          title="Нет каналов после фильтра языка"
          description="По выбранному фильтру RU/EN не осталось каналов с латиницей или кириллицей в названии видео. Отключите фильтр, чтобы увидеть полный список."
        />
      ) : null}

      {!initialLoading && !error && visibleChannels.length > 0 ? (
        <div className="space-y-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            {isLangFilterActive ? (
              <p className="text-sm text-muted-foreground">
                Показано{" "}
                <span className="font-semibold tabular-nums text-foreground">
                  {visibleChannels.length}
                </span>{" "}
                из {sortedChannels.length} каналов (фильтр RU/EN)
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">
                Отображается{" "}
                <span className="font-semibold tabular-nums text-foreground">
                  {visibleChannels.length}
                </span>{" "}
                каналов
              </p>
            )}

            <Button
              type="button"
              size="sm"
              className="w-full bg-gradient-to-r from-indigo-600 to-violet-600 text-white hover:from-indigo-500 hover:to-violet-500 sm:w-auto"
              disabled={aiLoading}
              onClick={() => void handleGenerateIdeas()}
            >
              {aiLoading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Генерация...
                </>
              ) : (
                <>
                  <Sparkles className="h-4 w-4" />
                  Сгенерировать идеи через AI
                </>
              )}
            </Button>
          </div>

          <div
            className={cn(
              "grid grid-cols-1 gap-5 transition-opacity md:grid-cols-2 lg:grid-cols-3",
              (isRefreshing || isScanning) && "opacity-60",
            )}
          >
            {visibleChannels.map((channel) => (
              <ExplosiveChannelCard key={channel.channel_id} channel={channel} />
            ))}
          </div>
        </div>
      ) : null}

      <AiIdeasModal
        open={aiModalOpen}
        loading={aiLoading}
        error={aiError}
        ideas={aiIdeas}
        onClose={() => setAiModalOpen(false)}
      />
    </div>
  );
}

function ExplosiveChannelsSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }).map((_, index) => (
        <Skeleton key={index} className="h-[420px] rounded-xl" />
      ))}
    </div>
  );
}

function ContentFormatToggle({
  label,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-3 rounded-xl border border-border/60 bg-card/80 px-4 py-3">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="h-4 w-4 shrink-0 rounded border-border accent-primary disabled:cursor-not-allowed disabled:opacity-50"
      />
      <span className="text-sm leading-snug">{label}</span>
    </label>
  );
}
