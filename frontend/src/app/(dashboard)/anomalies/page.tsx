"use client";

import { useCallback, useState } from "react";
import { Sparkles } from "lucide-react";
import { searchAnomalies } from "@/lib/api";
import type { ExtendedSearchResponse } from "@/lib/types";
import { AnomalyFiltersPanel, type AnomalyFilters } from "@/components/anomalies/filters-panel";
import { VideoCard } from "@/components/anomalies/video-card";
import { VideoGridSkeleton } from "@/components/anomalies/video-grid-skeleton";
import { Badge } from "@/components/ui/badge";
import { StateMessage } from "@/components/ui/state-message";

const defaultFilters: AnomalyFilters = {
  q: "",
  period: "week",
  durationMin: 0,
  durationMax: 3600,
  minVirality: 1000,
};

export default function AnomaliesPage() {
  const [filters, setFilters] = useState<AnomalyFilters>(defaultFilters);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ExtendedSearchResponse | null>(null);

  const handleSearch = useCallback(async () => {
    if (!filters.q.trim()) return;

    setLoading(true);
    setError(null);

    try {
      const data = await searchAnomalies({
        q: filters.q.trim(),
        period: filters.period,
        duration_min: filters.durationMin || undefined,
        duration_max: filters.durationMax || undefined,
        min_virality_percent: filters.minVirality || undefined,
        limit: 50,
      });
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка поиска");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, [filters]);

  return (
    <div className="space-y-6">
      <header>
        <div className="flex items-center gap-2">
          <Sparkles className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-bold tracking-tight">Поиск аномалий</h1>
        </div>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          Находите вирусные видео с аномально высоким соотношением просмотров к подписчикам канала.
        </p>
      </header>

      <AnomalyFiltersPanel
        filters={filters}
        loading={loading}
        onChange={setFilters}
        onSubmit={handleSearch}
      />

      {loading && <VideoGridSkeleton count={6} />}

      {!loading && error && (
        <StateMessage variant="error" title="Не удалось выполнить поиск" description={error} />
      )}

      {!loading && !error && result && (
        <section className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-lg font-semibold">
              Найдено: <span className="text-primary">{result.total}</span> видео
            </h2>
            {result.cached && <Badge variant="secondary">Из кэша</Badge>}
          </div>

          {result.items.length === 0 ? (
            <StateMessage
              title="Аномалии не найдены"
              description="Попробуйте ослабить фильтры или изменить ключевое слово."
            />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {result.items.map((video) => (
                <VideoCard key={video.video_id} video={video} />
              ))}
            </div>
          )}
        </section>
      )}

      {!loading && !error && !result && (
        <StateMessage
          title="Начните с ключевого слова"
          description="Введите нишу или запрос и нажмите «Найти аномалии», чтобы увидеть сетку вирусных видео."
        />
      )}
    </div>
  );
}
