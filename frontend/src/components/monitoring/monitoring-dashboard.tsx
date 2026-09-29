"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Radar, RefreshCw } from "lucide-react";

import {
  CycleStatusBadge,
  SystemStatusBadge,
} from "@/components/design-system/status-badges";
import {
  BreakoutVideosTable,
  PriorityVideosTable,
} from "@/components/monitoring/monitoring-video-table";
import {
  DataTableHead,
  DataTableRow,
  DataTableShell,
  DataTableTd,
  DataTableTh,
  Disclosure,
  EmptyState,
  InfoTooltip,
  LoadingState,
  Metric,
  MetricGroup,
  PageHeader,
  PageShell,
  RefreshingIndicator,
  SectionPanel,
  StaleDataWarning,
  SummaryStrip,
} from "@/components/design-system";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getMonitoringCycles,
  getMonitoringOverview,
  getMonitoringStatus,
  getMonitoringVideos,
} from "@/lib/api";
import {
  CHECKPOINT_HELP,
  breakoutMonitoringSummary,
  MONITORING_MODE_BREAKOUT_HELP,
  MONITORING_MODE_PRIORITY_HELP,
  monitoringWorkerSummaryLine,
  priorityMonitoringSummary,
  TIER_OPERATIONAL_HELP,
} from "@/lib/monitoring-summaries";
import {
  formatDateTimeLocal,
  formatMonitoringVph,
  shortenRunId,
} from "@/lib/monitoring-format";
import { formatCount } from "@/lib/operations-format";
import type {
  MonitoringCycle,
  MonitoringOverview,
  MonitoringVideoListItem,
  MonitoringVideoSort,
  MonitoringVideoStatusFilter,
  MonitoringWorkerStatus,
} from "@/lib/monitoring-types";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;
const POLL_MS = 60_000;

type ViewMode = "priority" | "breakout";

const PRIORITY_ALT_SORT: { value: MonitoringVideoSort; label: string }[] = [
  { value: "priority", label: "Очередь (по умолчанию)" },
  { value: "vph_desc", label: "VPH ↓" },
  { value: "views_desc", label: "Просмотры ↓" },
  { value: "age_asc", label: "Возраст ↑" },
  { value: "latest_snapshot_desc", label: "Последний снимок ↓" },
];

const STATUS_FILTER_OPTIONS: { value: "" | MonitoringVideoStatusFilter; label: string }[] = [
  { value: "", label: "Все состояния" },
  { value: "overdue", label: "Просрочено" },
  { value: "due", label: "Пора обработать" },
  { value: "pending", label: "Ожидает checkpoint" },
  { value: "active", label: "На контроле" },
  { value: "stopped", label: "Снято с мониторинга" },
];

export function MonitoringDashboard() {
  const [workerStatus, setWorkerStatus] = useState<MonitoringWorkerStatus | null>(null);
  const [overview, setOverview] = useState<MonitoringOverview | null>(null);
  const [videos, setVideos] = useState<MonitoringVideoListItem[]>([]);
  const [videosTotal, setVideosTotal] = useState(0);
  const [cycles, setCycles] = useState<MonitoringCycle[]>([]);

  const [overviewLoading, setOverviewLoading] = useState(true);
  const [videosLoading, setVideosLoading] = useState(true);
  const [cyclesLoading, setCyclesLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [videosError, setVideosError] = useState<string | null>(null);
  const [cyclesError, setCyclesError] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const [viewMode, setViewMode] = useState<ViewMode>("priority");
  const [tierFilter, setTierFilter] = useState<"" | "A" | "B" | "C">("");
  const [statusFilter, setStatusFilter] = useState<"" | MonitoringVideoStatusFilter>("");
  const [prioritySort, setPrioritySort] = useState<MonitoringVideoSort>("priority");
  const [titleSearch, setTitleSearch] = useState("");
  const [offset, setOffset] = useState(0);

  const inFlight = useRef(false);
  const videosLoaded = useRef(false);

  const effectiveSort: MonitoringVideoSort = viewMode === "breakout" ? "breakout_v1" : prioritySort;

  const loadOverviewBundle = useCallback(async (isBackground: boolean) => {
    if (!isBackground) {
      setOverviewLoading(true);
    }
    if (!isBackground) {
      setOverviewError(null);
    }
    try {
      const [status, overviewData] = await Promise.all([
        getMonitoringStatus(),
        getMonitoringOverview(),
      ]);
      setWorkerStatus(status);
      setOverview(overviewData);
      if (isBackground) {
        setRefreshError(null);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Не удалось загрузить обзор";
      if (!isBackground) {
        setOverviewError(message);
      } else {
        setRefreshError(message);
      }
    } finally {
      setOverviewLoading(false);
    }
  }, []);

  const loadVideos = useCallback(
    async (isBackground: boolean) => {
      if (!isBackground) {
        setVideosLoading(true);
      }
      if (!isBackground) {
        setVideosError(null);
      }
      try {
        const response = await getMonitoringVideos({
          tier: tierFilter || undefined,
          status: viewMode === "breakout" ? undefined : statusFilter || undefined,
          keyword: titleSearch.trim() || undefined,
          sort: effectiveSort,
          limit: PAGE_SIZE,
          offset,
        });
        setVideos(response.items);
        setVideosTotal(response.total);
        videosLoaded.current = true;
        setRefreshError(null);
      } catch (err) {
        const message = err instanceof Error ? err.message : "Не удалось загрузить видео";
        if (!videosLoaded.current) {
          setVideosError(message);
        } else {
          setVideosError(message);
          setRefreshError(message);
        }
      } finally {
        setVideosLoading(false);
      }
    },
    [effectiveSort, offset, statusFilter, tierFilter, titleSearch, viewMode],
  );

  const loadCycles = useCallback(async (isBackground: boolean) => {
    if (!isBackground) {
      setCyclesLoading(true);
    }
    setCyclesError(null);
    try {
      const response = await getMonitoringCycles({ limit: 10 });
      setCycles(response.items);
    } catch (err) {
      setCyclesError(err instanceof Error ? err.message : "Не удалось загрузить циклы");
    } finally {
      setCyclesLoading(false);
    }
  }, []);

  const refreshAll = useCallback(
    async (isBackground = false) => {
      if (inFlight.current) {
        return;
      }
      inFlight.current = true;
      setRefreshing(true);
      try {
        await Promise.all([
          loadOverviewBundle(isBackground),
          loadVideos(isBackground),
          loadCycles(isBackground),
        ]);
      } finally {
        inFlight.current = false;
        setRefreshing(false);
      }
    },
    [loadCycles, loadOverviewBundle, loadVideos],
  );

  useEffect(() => {
    void loadOverviewBundle(false);
    void loadCycles(false);
  }, [loadOverviewBundle, loadCycles]);

  useEffect(() => {
    void loadVideos(false);
  }, [loadVideos]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") {
        return;
      }
      void loadOverviewBundle(true);
      void loadVideos(true);
      void loadCycles(true);
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [loadCycles, loadOverviewBundle, loadVideos]);

  const snapshotReferenceMs = workerStatus?.current_time
    ? new Date(workerStatus.current_time).getTime()
    : Date.now();

  const pageIndex = Math.floor(offset / PAGE_SIZE) + 1;
  const pageCount = Math.max(1, Math.ceil(videosTotal / PAGE_SIZE));

  const prioritySummary = priorityMonitoringSummary(overview, { loading: overviewLoading });
  const breakoutSummary = breakoutMonitoringSummary(
    viewMode === "breakout" ? videosTotal : 0,
    overview?.active_monitored_count ?? 0,
  );

  const topVphHint = useMemo(() => {
    if (viewMode !== "breakout" || videos.length === 0) {
      return null;
    }
    const top = videos[0];
    const vph = top.current_vph ?? top.breakout_ranking_value;
    if (vph == null) {
      return null;
    }
    return formatMonitoringVph(vph);
  }, [videos, viewMode]);

  const workerLine = monitoringWorkerSummaryLine(workerStatus);

  const emptyVideosTitle =
    viewMode === "breakout"
      ? "Сейчас нет видео, подходящих для breakout-рейтинга."
      : "Сейчас нет видео, которым пора делать следующий снимок.";

  const emptyVideosDescription =
    viewMode === "breakout" && (overview?.active_monitored_count ?? 0) > 0
      ? "Видео в базе есть, но они не подходят под текущие правила breakout-анализа."
      : viewMode === "priority" && (overview?.active_monitored_count ?? 0) === 0
        ? "Нет подходящих regular/medium/long записей с метриками для планировщика."
        : undefined;

  return (
    <PageShell className="pb-10">
      <PageHeader
        icon={<Radar className="h-6 w-6 text-primary" aria-hidden />}
        title="Мониторинг"
        lead="Повторные снимки метрик для видео из базы. Два режима: очередь обработки и аналитический рейтинг."
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refreshAll(false)}
            disabled={refreshing}
            data-testid="monitoring-refresh"
          >
            <RefreshCw className={cn("mr-2 h-4 w-4", refreshing && "animate-spin")} aria-hidden />
            Обновить
          </Button>
        }
      />

      {workerStatus ? (
        <div className="flex flex-wrap items-center gap-2">
          <SystemStatusBadge state={workerStatus.status} title={workerLine ?? undefined} />
          {workerStatus.lock_holder ? (
            <span className="text-xs text-muted-foreground">{workerStatus.lock_holder}</span>
          ) : null}
        </div>
      ) : null}

      <RefreshingIndicator visible={refreshing && videos.length > 0} />

      {refreshError && (overview || videosLoaded.current) ? (
        <StaleDataWarning message={`Ошибка обновления: ${refreshError}. Показаны последние успешные данные.`} />
      ) : null}

      {overviewError && !overview ? (
        <StaleDataWarning message={overviewError} />
      ) : null}

      <div
        className="inline-flex rounded-lg border border-border/70 p-1"
        role="tablist"
        aria-label="Режим мониторинга"
      >
        <Button
          type="button"
          variant={viewMode === "priority" ? "secondary" : "ghost"}
          size="sm"
          role="tab"
          aria-selected={viewMode === "priority"}
          data-testid="monitoring-mode-priority"
          onClick={() => {
            setViewMode("priority");
            setOffset(0);
          }}
        >
          Приоритет
        </Button>
        <Button
          type="button"
          variant={viewMode === "breakout" ? "secondary" : "ghost"}
          size="sm"
          role="tab"
          aria-selected={viewMode === "breakout"}
          data-testid="monitoring-mode-breakout"
          onClick={() => {
            setViewMode("breakout");
            setOffset(0);
            setStatusFilter("");
          }}
        >
          Breakout v1
        </Button>
      </div>

      {viewMode === "priority" ? (
        <SummaryStrip
          tone={prioritySummary.tone}
          lines={prioritySummary.lines}
          data-testid="monitoring-priority-summary"
        />
      ) : (
        <SummaryStrip
          tone={breakoutSummary.tone}
          lines={breakoutSummary.lines}
          data-testid="monitoring-breakout-summary"
        />
      )}

      <p className="text-sm text-muted-foreground" data-testid="monitoring-mode-help">
        {viewMode === "priority" ? MONITORING_MODE_PRIORITY_HELP : MONITORING_MODE_BREAKOUT_HELP}
      </p>

      {viewMode === "priority" && !overviewLoading && overview ? (
        <MetricGroup>
          <Metric label="Пора обработать" value={formatCount(overview.due_count)} />
          <Metric label="Просрочено" value={formatCount(overview.overdue_count)} />
          <Metric label="На мониторинге" value={formatCount(overview.active_monitored_count)} />
        </MetricGroup>
      ) : null}

      {viewMode === "breakout" && !videosLoading ? (
        <MetricGroup>
          <Metric label="В рейтинге" value={formatCount(videosTotal)} />
          {topVphHint ? (
            <Metric label="VPH лидера на странице" value={topVphHint} tooltip={MONITORING_MODE_BREAKOUT_HELP} />
          ) : null}
        </MetricGroup>
      ) : null}

      <SectionPanel title={viewMode === "priority" ? "Очередь мониторинга" : "Breakout v1"}>
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-2">
            <Select
              value={tierFilter}
              onChange={(e) => {
                setOffset(0);
                setTierFilter(e.target.value as "" | "A" | "B" | "C");
              }}
              className="w-[130px]"
              aria-label="Tier"
            >
              <option value="">Tier: все</option>
              <option value="A">Tier A</option>
              <option value="B">Tier B</option>
              <option value="C">Tier C</option>
            </Select>
            <InfoTooltip content={TIER_OPERATIONAL_HELP} />
            {viewMode === "priority" ? (
              <Select
                value={statusFilter}
                onChange={(e) => {
                  setOffset(0);
                  setStatusFilter(e.target.value as "" | MonitoringVideoStatusFilter);
                }}
                className="w-[180px]"
                aria-label="Состояние"
              >
                {STATUS_FILTER_OPTIONS.map((opt) => (
                  <option key={opt.value || "all"} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </Select>
            ) : null}
            <Input
              placeholder="Поиск по названию"
              value={titleSearch}
              onChange={(e) => setTitleSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  setOffset(0);
                  void loadVideos(false);
                }
              }}
              className="w-[200px]"
            />
            <Button variant="secondary" size="sm" onClick={() => void loadVideos(false)}>
              Применить
            </Button>
          </div>

          <Disclosure summary="Дополнительные фильтры">
            {viewMode === "priority" ? (
              <div className="space-y-3">
                <label className="flex flex-col gap-1 text-sm">
                  <span className="text-muted-foreground">Сортировка очереди</span>
                  <Select
                    value={prioritySort}
                    onChange={(e) => {
                      setOffset(0);
                      setPrioritySort(e.target.value as MonitoringVideoSort);
                    }}
                    className="max-w-xs"
                  >
                    {PRIORITY_ALT_SORT.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </Select>
                </label>
                <p className="text-xs text-muted-foreground">{CHECKPOINT_HELP}</p>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">{MONITORING_MODE_BREAKOUT_HELP}</p>
            )}
          </Disclosure>
        </div>

        {videosError && !videosLoaded.current ? (
          <EmptyState title="Не удалось загрузить список" description={videosError} variant="unavailable" />
        ) : null}

        {videosError && videosLoaded.current ? (
          <p className="text-sm text-destructive" role="alert">
            {videosError}
          </p>
        ) : null}

        <div className="relative mt-3">
          {videosLoading && videos.length === 0 && !videosError ? (
            <LoadingState variant="block" title="Загрузка видео…" />
          ) : null}

          {videos.length === 0 && !videosLoading && !videosError ? (
            <EmptyState title={emptyVideosTitle} description={emptyVideosDescription} />
          ) : null}

          {videos.length > 0 ? (
            <div
              className={cn(videosLoading && "opacity-70")}
              data-testid={viewMode === "priority" ? "monitoring-priority-table" : "monitoring-breakout-table"}
            >
              {viewMode === "priority" ? (
                <PriorityVideosTable videos={videos} referenceMs={snapshotReferenceMs} />
              ) : (
                <BreakoutVideosTable videos={videos} referenceMs={snapshotReferenceMs} />
              )}
            </div>
          ) : null}
        </div>

        <div className="flex items-center justify-between gap-2 text-sm">
          <span className="text-muted-foreground">
            Всего {videosTotal} · страница {pageIndex} из {pageCount}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={offset <= 0 || videosLoading}
              onClick={() => setOffset((v) => Math.max(0, v - PAGE_SIZE))}
            >
              Назад
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={offset + PAGE_SIZE >= videosTotal || videosLoading}
              onClick={() => setOffset((v) => v + PAGE_SIZE)}
            >
              Вперёд
            </Button>
          </div>
        </div>
      </SectionPanel>

      <Disclosure summary="Последний цикл и техническая сводка">
        {overviewLoading && !overview?.latest_cycle ? (
          <Skeleton className="h-20 w-full" />
        ) : overview?.latest_cycle ? (
          <dl className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <dt className="text-muted-foreground">Run ID</dt>
              <dd className="font-mono text-xs">{shortenRunId(overview.latest_cycle.run_id)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Завершён</dt>
              <dd>{formatDateTimeLocal(overview.latest_cycle.finished_at)}</dd>
            </div>
            <div className="flex items-center gap-2">
              <dt className="text-muted-foreground">Статус</dt>
              <dd>
                <CycleStatusBadge status={overview.latest_cycle.cycle_status} />
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Загружено</dt>
              <dd>{overview.latest_cycle.loaded_video_count}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Выбрано</dt>
              <dd>{overview.latest_cycle.selected_request_count}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Снимков сохранено</dt>
              <dd>{overview.latest_cycle.inserted_snapshot_count}</dd>
            </div>
          </dl>
        ) : (
          <p className="text-sm text-muted-foreground" data-testid="monitoring-no-cycles">
            Нет сохранённых циклов. После первого запуска воркера здесь появится сводка.
          </p>
        )}
      </Disclosure>

      <SectionPanel title="Недавние циклы">
        {cyclesError ? (
          <p className="text-sm text-destructive">
            {cyclesError}
            <Button variant="ghost" className="ml-2 h-auto p-0" onClick={() => void loadCycles(false)}>
              Повторить
            </Button>
          </p>
        ) : null}
        {cyclesLoading && cycles.length === 0 ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <DataTableShell minWidthClassName="min-w-[640px]" className="text-sm">
            <DataTableHead>
              <tr>
                <DataTableTh>Время</DataTableTh>
                <DataTableTh>Статус</DataTableTh>
                <DataTableTh align="right">Загружено</DataTableTh>
                <DataTableTh align="right">Выбрано</DataTableTh>
                <DataTableTh align="right">Сохранено</DataTableTh>
                <DataTableTh align="right">Сбоев</DataTableTh>
                <DataTableTh align="right">Длительность</DataTableTh>
              </tr>
            </DataTableHead>
            <tbody>
              {cycles.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-3 py-6 text-center text-muted-foreground">
                    История циклов пуста.
                  </td>
                </tr>
              ) : (
                cycles.map((cycle) => (
                  <DataTableRow key={cycle.run_id}>
                    <DataTableTd>{formatDateTimeLocal(cycle.finished_at ?? cycle.started_at)}</DataTableTd>
                    <DataTableTd>
                      <CycleStatusBadge status={cycle.cycle_status} />
                    </DataTableTd>
                    <DataTableTd align="right">{cycle.loaded}</DataTableTd>
                    <DataTableTd align="right">{cycle.selected}</DataTableTd>
                    <DataTableTd align="right">{cycle.inserted}</DataTableTd>
                    <DataTableTd align="right">
                      {cycle.fetch_failed + cycle.validation_failed + cycle.persistence_failed}
                    </DataTableTd>
                    <DataTableTd align="right">{cycle.runtime_seconds.toFixed(1)} с</DataTableTd>
                  </DataTableRow>
                ))
              )}
            </tbody>
          </DataTableShell>
        )}
      </SectionPanel>
    </PageShell>
  );
}
