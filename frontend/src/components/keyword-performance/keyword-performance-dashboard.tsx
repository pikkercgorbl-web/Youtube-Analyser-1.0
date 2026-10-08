"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BarChart3, RefreshCw } from "lucide-react";

import {
  Disclosure,
  EmptyState,
  HelpText,
  LoadingState,
  PageHeader,
  PageShell,
  RefreshingIndicator,
  SectionPanel,
  StaleDataWarning,
  SummaryStrip,
  ZeroContextNote,
} from "@/components/design-system";
import {
  BreakoutPerformanceTable,
  DiscoveryPerformanceTable,
  OutcomesPerformanceTable,
} from "@/components/keyword-performance/keyword-performance-tables";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { fetchKeywordPerformanceList } from "@/lib/api";
import {
  ATTRIBUTION_ALL_HITS,
  ATTRIBUTION_FIRST_DISCOVERY,
  BREAKOUT_TOP_DECILE_HELP,
  EVIDENCE_NOT_QUALITY,
  MISSING_72H_HELP,
  OUTCOME_72H_TOOLTIP,
} from "@/lib/keyword-performance-copy";
import {
  breakoutListSummary,
  discoveryListSummary,
  outcomesListSummary,
} from "@/lib/keyword-performance-summaries";
import {
  cacheKeyForPerformance,
  metricFamilyFetchFlags,
  type KeywordAttributionMode,
  type KeywordPerformanceListResponse,
  type KeywordPerformanceMetricFamily,
} from "@/lib/keyword-performance-types";
import { formatDateTimeLocal } from "@/lib/monitoring-format";
import { cn } from "@/lib/utils";

const LIMIT_OPTIONS = [50, 100, 500] as const;

type ActiveMetricFamily = Exclude<KeywordPerformanceMetricFamily, "full">;

const METRIC_FAMILIES: { id: ActiveMetricFamily; label: string }[] = [
  { id: "discovery", label: "Discovery" },
  { id: "breakout", label: "Breakout" },
  { id: "outcomes", label: "72h исходы" },
];

export function KeywordPerformanceDashboard() {
  const [metricFamily, setMetricFamily] =
    useState<ActiveMetricFamily>("discovery");
  const [attribution, setAttribution] =
    useState<KeywordAttributionMode>("all_hits");
  const [limit, setLimit] = useState<number>(100);
  const [search, setSearch] = useState("");
  const [lifecycleFilter, setLifecycleFilter] = useState("");

  const [response, setResponse] =
    useState<KeywordPerformanceListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const cacheRef = useRef<Map<string, KeywordPerformanceListResponse>>(
    new Map(),
  );
  const inFlight = useRef(false);
  const hasLoaded = useRef(false);

  const load = useCallback(
    async (family: ActiveMetricFamily, force = false) => {
      const key = cacheKeyForPerformance(family, attribution, limit);
      if (!force && cacheRef.current.has(key)) {
        setResponse(cacheRef.current.get(key)!);
        setError(null);
        setLoading(false);
        return;
      }
      if (inFlight.current) {
        return;
      }
      inFlight.current = true;
      setLoading(true);
      if (!hasLoaded.current) {
        setError(null);
      }
      try {
        const flags = metricFamilyFetchFlags(family);
        const data = await fetchKeywordPerformanceList({
          limit,
          attribution_mode: attribution,
          ...flags,
        });
        cacheRef.current.set(key, data);
        setResponse(data);
        setRefreshError(null);
        hasLoaded.current = true;
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Не удалось загрузить метрики";
        if (!hasLoaded.current) {
          setError(message);
          setResponse(null);
        } else {
          setRefreshError(message);
        }
      } finally {
        setLoading(false);
        inFlight.current = false;
      }
    },
    [attribution, limit],
  );

  useEffect(() => {
    void load(metricFamily);
  }, [metricFamily, attribution, limit, load]);

  const items = useMemo(() => response?.items ?? [], [response?.items]);
  const globalEligible = response?.global_eligible_video_count;
  const referenceIso = response?.evaluated_at ?? null;

  const filteredItems = useMemo(() => {
    let list = items;
    const q = search.trim().toLowerCase();
    if (q) {
      list = list.filter((row) => row.keyword.toLowerCase().includes(q));
    }
    if (lifecycleFilter) {
      list = list.filter(
        (row) => (row.lifecycle_status ?? "") === lifecycleFilter,
      );
    }
    return list;
  }, [items, lifecycleFilter, search]);

  const summary = useMemo(() => {
    if (metricFamily === "discovery") {
      return discoveryListSummary(filteredItems);
    }
    if (metricFamily === "breakout") {
      return breakoutListSummary(filteredItems, globalEligible);
    }
    return outcomesListSummary(filteredItems);
  }, [filteredItems, globalEligible, metricFamily]);

  const totalObserved72h = items.reduce(
    (s, r) => s + (r.observed_72h_video_count ?? 0),
    0,
  );

  return (
    <div data-testid="keyword-performance-dashboard">
      <PageShell>
        <PageHeader
          icon={<BarChart3 className="h-6 w-6 text-primary" aria-hidden />}
          title="Отдача запросов"
          lead="Какие поисковые запросы приносят новые видео и как меняются результаты находок через 72 часа."
          actions={
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={loading}
              data-testid="kp-refresh"
              onClick={() => {
                cacheRef.current.delete(
                  cacheKeyForPerformance(metricFamily, attribution, limit),
                );
                void load(metricFamily, true);
              }}
            >
              <RefreshCw
                className={cn("mr-2 h-4 w-4", loading && "animate-spin")}
                aria-hidden
              />
              Обновить
            </Button>
          }
        />

        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">Семейство метрик</p>
            <div
              className="flex flex-wrap gap-1"
              role="tablist"
              aria-label="Семейство метрик"
            >
              {METRIC_FAMILIES.map(({ id, label }) => (
                <Button
                  key={id}
                  type="button"
                  size="sm"
                  variant={metricFamily === id ? "default" : "outline"}
                  data-testid={`metric-family-${id}`}
                  onClick={() => setMetricFamily(id)}
                >
                  {label}
                </Button>
              ))}
            </div>
          </div>

          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">Атрибуция</p>
            <Select
              data-testid="attribution-mode"
              value={attribution}
              onChange={(e) =>
                setAttribution(e.target.value as KeywordAttributionMode)
              }
              className="min-w-[180px]"
            >
              <option value="all_hits">Все находки</option>
              <option value="first_discovery">Первый источник</option>
            </Select>
          </div>

          <Input
            placeholder="Поиск по ключу"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-[200px]"
            aria-label="Поиск по ключу"
          />
        </div>

        <div
          className="space-y-1 text-xs text-muted-foreground"
          data-testid="attribution-help"
        >
          <p>
            <span className="font-medium text-foreground">Все находки:</span>{" "}
            {ATTRIBUTION_ALL_HITS}
          </p>
          <p>
            <span className="font-medium text-foreground">
              Первый источник:
            </span>{" "}
            {ATTRIBUTION_FIRST_DISCOVERY}
          </p>
        </div>

        <SummaryStrip
          tone={summary.tone}
          lines={summary.lines}
          data-testid="kp-summary-strip"
        />

        <HelpText>{EVIDENCE_NOT_QUALITY}</HelpText>

        {metricFamily === "breakout" ? (
          <div className="space-y-2">
            <p
              className="text-sm text-muted-foreground"
              data-testid="breakout-explainer"
            >
              {BREAKOUT_TOP_DECILE_HELP}
            </p>
            {response ? (
              <p
                className="text-xs text-muted-foreground"
                data-testid="evaluation-context"
              >
                Оценка: {formatDateTimeLocal(response.evaluated_at)}
                {response.ranking_version
                  ? ` · ${response.ranking_version}`
                  : null}
                {globalEligible != null
                  ? ` · глобально подходят ${globalEligible}`
                  : null}
              </p>
            ) : null}
            {globalEligible === 0 ? (
              <div data-testid="breakout-global-unavailable">
                <ZeroContextNote>
                  Сейчас нет видео, подходящих для глобального
                  breakout-рейтинга. Не интерпретируйте нулевые доли как
                  «плохие» ключи.
                </ZeroContextNote>
              </div>
            ) : null}
          </div>
        ) : null}

        {metricFamily === "outcomes" ? (
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">
              {OUTCOME_72H_TOOLTIP}
            </p>
            {totalObserved72h === 0 && items.length > 0 ? (
              <div data-testid="outcomes-none-yet">
                <ZeroContextNote>
                  Валидных ~72h исходов пока нет. Отсутствие исходов не означает
                  нулевое качество keyword.
                </ZeroContextNote>
              </div>
            ) : null}
            <HelpText>{MISSING_72H_HELP}</HelpText>
          </div>
        ) : null}

        <Disclosure summary="Дополнительные фильтры">
          <div className="flex flex-wrap gap-4">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted-foreground">Лимит (сервер)</span>
              <Select
                data-testid="limit-select"
                value={String(limit)}
                onChange={(e) => setLimit(Number(e.target.value))}
                className="min-w-[100px]"
              >
                {LIMIT_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </Select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted-foreground">Lifecycle</span>
              <Select
                value={lifecycleFilter}
                onChange={(e) => setLifecycleFilter(e.target.value)}
                className="min-w-[140px]"
              >
                <option value="">Все</option>
                <option value="probation">Пробный</option>
                <option value="active">В работе</option>
                <option value="weak">Слабый сигнал</option>
                <option value="archived">Архив</option>
              </Select>
            </label>
          </div>
        </Disclosure>

        <RefreshingIndicator visible={loading && hasLoaded.current} />

        {refreshError && hasLoaded.current ? (
          <StaleDataWarning
            message={`Ошибка обновления: ${refreshError}. Показаны последние успешные данные.`}
          />
        ) : null}

        {loading && !response ? (
          <LoadingState variant="block" title="Загрузка метрик…" />
        ) : null}

        {!loading && error && !response ? (
          <div data-testid="api-error">
            <EmptyState
              title="Ошибка API"
              description={error}
              variant="unavailable"
            />
          </div>
        ) : null}

        {!error && response && filteredItems.length === 0 ? (
          <EmptyState
            title="Нет ключевых слов"
            description={
              items.length > 0
                ? "Фильтр поиска или lifecycle не вернул строк."
                : "Очередь target keywords пуста или лимит не вернул строк."
            }
            data-testid="empty-keywords"
          />
        ) : null}

        {!error && filteredItems.length > 0 ? (
          <SectionPanel title="Ключевые слова">
            <div className={cn(loading && "opacity-60")}>
              {metricFamily === "discovery" ? (
                <div data-testid="discovery-table">
                  <DiscoveryPerformanceTable
                    items={filteredItems}
                    referenceIso={referenceIso}
                  />
                </div>
              ) : null}
              {metricFamily === "breakout" ? (
                <div data-testid="breakout-table">
                  <BreakoutPerformanceTable
                    items={filteredItems}
                    globalEligible={globalEligible}
                  />
                </div>
              ) : null}
              {metricFamily === "outcomes" ? (
                <div data-testid="outcomes-table">
                  <OutcomesPerformanceTable items={filteredItems} />
                </div>
              ) : null}
            </div>
          </SectionPanel>
        ) : null}
      </PageShell>
    </div>
  );
}
