"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { KeyRound, RefreshCw } from "lucide-react";

import {
  EmptyState,
  HelpText,
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
import { StateMessage } from "@/components/ui/state-message";
import { KeywordPoolTable } from "@/components/keyword-pool/keyword-pool-table";
import { fetchTargetKeywords } from "@/lib/api";
import {
  ARCHIVED_POOL_HELP,
  CLIENT_FILTER_NOTE,
  POOL_LIFECYCLE_HELP,
  poolLifecycleLabel,
  poolSourceLabel,
} from "@/lib/keyword-pool-copy";
import { filterPoolRows, sortPoolRows } from "@/lib/keyword-pool-filter-sort";
import type {
  PoolDueFilter,
  PoolLifecycleFilter,
  PoolSortKey,
  PoolSourceFilter,
  TargetKeywordItem,
} from "@/lib/keyword-pool-types";
import {
  computePoolMetrics,
  poolDueEmptyNote,
  poolSummaryLines,
} from "@/lib/keyword-pool-summaries";
import { formatCount } from "@/lib/operations-format";
import { cn } from "@/lib/utils";

const POLL_MS = 60_000;

export function KeywordPoolDashboard() {
  const [rows, setRows] = useState<TargetKeywordItem[] | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [lifecycle, setLifecycle] = useState<PoolLifecycleFilter>("all");
  const [source, setSource] = useState<PoolSourceFilter>("all");
  const [due, setDue] = useState<PoolDueFilter>("all");
  const [sortKey, setSortKey] = useState<PoolSortKey>("next_scan_at");
  const hasLoaded = useRef(false);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const load = useCallback(async (opts?: { silent?: boolean }) => {
    const silent = opts?.silent ?? false;
    if (!silent) {
      if (!hasLoaded.current) {
        setInitialLoading(true);
      } else {
        setRefreshing(true);
      }
    }
    if (!hasLoaded.current) {
      setError(null);
    }
    try {
      const data = await fetchTargetKeywords();
      setRows(data);
      setNowMs(Date.now());
      hasLoaded.current = true;
      setError(null);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Не удалось загрузить пул ключей";
      setError(message);
      if (!hasLoaded.current) {
        setRows(null);
      }
    } finally {
      setInitialLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const id = window.setInterval(() => {
      void load({ silent: true });
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [load]);

  const now = useMemo(() => new Date(nowMs), [nowMs]);

  const metrics = useMemo(
    () => computePoolMetrics(rows ?? [], now),
    [rows, now],
  );

  const keywordById = useMemo(() => {
    const map = new Map<number, string>();
    for (const row of rows ?? []) {
      map.set(row.id, row.keyword);
    }
    return map;
  }, [rows]);

  const filtered = useMemo(() => {
    const list = filterPoolRows(rows ?? [], {
      search,
      lifecycle,
      source,
      due,
      now,
    });
    return sortPoolRows(list, sortKey, now);
  }, [rows, search, lifecycle, source, due, sortKey, now]);

  const summaryLines = poolSummaryLines(metrics);
  const dueNote = poolDueEmptyNote(metrics);

  return (
    <PageShell>
      <PageHeader
        title="Поисковые запросы"
        lead="Управляйте направлениями поиска: происхождение запросов, их статус и время следующего прохода."
        icon={
          <KeyRound className="h-6 w-6 shrink-0 text-primary" aria-hidden />
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="gap-2"
          disabled={refreshing}
          onClick={() => void load()}
        >
          <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
          Обновить
        </Button>
        <RefreshingIndicator visible={refreshing} />
      </div>

      {error && rows ? (
        <StaleDataWarning
          message={`Ошибка обновления: ${error}. Показаны последние успешные данные.`}
        />
      ) : null}

      {initialLoading && !rows ? (
        <LoadingState title="Загрузка пула ключей…" />
      ) : null}

      {error && !rows ? (
        <StateMessage variant="error" title="Ошибка" description={error} />
      ) : null}

      {rows ? (
        <>
          <SummaryStrip
            tone={metrics.dueNow > 0 ? "warning" : "neutral"}
            lines={summaryLines}
          />

          <HelpText>{POOL_LIFECYCLE_HELP}</HelpText>
          <p className="text-xs text-muted-foreground">{ARCHIVED_POOL_HELP}</p>

          <MetricGroup title="Состояние пула">
            <Metric
              label="Всего ключей"
              value={formatCount(metrics.total)}
              testId="metric-pool-total"
            />
            <Metric
              label="Пробный"
              value={formatCount(metrics.probation)}
              tooltip={poolLifecycleLabel("probation")}
            />
            <Metric
              label="Активный"
              value={formatCount(metrics.active)}
              tooltip={poolLifecycleLabel("active")}
            />
            <Metric
              label="Редкий"
              value={formatCount(metrics.weak)}
              tooltip="Редкое расписание сканирования — не оценка качества."
            />
            <Metric label="Архив" value={formatCount(metrics.archived)} />
            <Metric
              label="Пора сканировать"
              value={formatCount(metrics.dueNow)}
              testId="metric-pool-due"
            />
            <Metric
              label="Скан в 24 ч"
              value={formatCount(metrics.scheduledNext24h)}
              tooltip="Ключи с next_scan_at в ближайшие 24 часа (ещё не просрочены)."
            />
          </MetricGroup>

          {dueNote ? (
            <p
              className="text-sm text-muted-foreground"
              data-testid="pool-no-due-note"
            >
              {dueNote}
            </p>
          ) : null}

          <SectionPanel title="Ключи" description={CLIENT_FILTER_NOTE}>
            <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:flex-wrap lg:items-end">
              <label className="flex min-w-[200px] flex-1 flex-col gap-1 text-xs">
                <span className="text-muted-foreground">Поиск</span>
                <Input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Фильтр по тексту…"
                  data-testid="pool-filter-search"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs">
                <span className="inline-flex items-center gap-1 text-muted-foreground">
                  Lifecycle
                  <InfoTooltip content={POOL_LIFECYCLE_HELP} />
                </span>
                <Select
                  value={lifecycle}
                  onChange={(e) =>
                    setLifecycle(e.target.value as PoolLifecycleFilter)
                  }
                  className="min-w-[140px]"
                  data-testid="pool-filter-lifecycle"
                >
                  <option value="all">Все</option>
                  <option value="probation">
                    {poolLifecycleLabel("probation")}
                  </option>
                  <option value="active">{poolLifecycleLabel("active")}</option>
                  <option value="weak">{poolLifecycleLabel("weak")}</option>
                  <option value="archived">
                    {poolLifecycleLabel("archived")}
                  </option>
                </Select>
              </label>
              <label className="flex flex-col gap-1 text-xs">
                <span className="text-muted-foreground">Источник</span>
                <Select
                  value={source}
                  onChange={(e) =>
                    setSource(e.target.value as PoolSourceFilter)
                  }
                  className="min-w-[160px]"
                >
                  <option value="all">Все</option>
                  <option value="seed">{poolSourceLabel("seed")}</option>
                  <option value="suggestion">
                    {poolSourceLabel("suggestion")}
                  </option>
                  <option value="related">{poolSourceLabel("related")}</option>
                  <option value="channel">{poolSourceLabel("channel")}</option>
                  <option value="manual">{poolSourceLabel("manual")}</option>
                  <option value="llm">{poolSourceLabel("llm")}</option>
                </Select>
              </label>
              <label className="flex flex-col gap-1 text-xs">
                <span className="text-muted-foreground">Очередь скана</span>
                <Select
                  value={due}
                  onChange={(e) => setDue(e.target.value as PoolDueFilter)}
                  className="min-w-[200px]"
                  data-testid="pool-filter-due"
                >
                  <option value="all">Все</option>
                  <option value="due">Пора сканировать</option>
                  <option value="next_24h">В ближайшие 24 ч</option>
                  <option value="unscheduled_or_archived">
                    Не запланировано / архив
                  </option>
                </Select>
              </label>
              <label className="flex flex-col gap-1 text-xs">
                <span className="text-muted-foreground">Сортировка</span>
                <Select
                  value={sortKey}
                  onChange={(e) => setSortKey(e.target.value as PoolSortKey)}
                  className="min-w-[180px]"
                >
                  <option value="next_scan_at">Сначала очередь скана</option>
                  <option value="keyword">По keyword</option>
                  <option value="lifecycle">По lifecycle</option>
                  <option value="last_checked">По последнему скану</option>
                </Select>
              </label>
            </div>

            {metrics.total === 0 ? (
              <EmptyState
                title="Пул ключей пуст."
                description="Добавьте ключи через исследование ниш или backend-очередь."
                compact
              />
            ) : filtered.length === 0 ? (
              <EmptyState
                title="Нет ключей по фильтрам"
                description="Измените фильтры или сбросьте поиск."
                compact
              />
            ) : (
              <KeywordPoolTable
                rows={filtered}
                keywordById={keywordById}
                now={now}
              />
            )}
          </SectionPanel>
        </>
      ) : null}
    </PageShell>
  );
}
