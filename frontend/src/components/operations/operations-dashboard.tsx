"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, RefreshCw } from "lucide-react";

import {
  Disclosure,
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
  SystemStatusBadge,
  ZeroContextNote,
} from "@/components/design-system";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StateMessage } from "@/components/ui/state-message";
import { DiscoveryCyclesTable, MonitoringCyclesTable } from "@/components/operations/operations-cycle-tables";
import { getOperationsOverview } from "@/lib/api";
import { METRIC_TOOLTIPS } from "@/lib/design-system/labels";
import { surfaces } from "@/lib/design-system/layout";
import {
  discoveryOperationsSummary,
  LIVENESS_DISCLAIMER,
  monitoringOperationsSummary,
  operationsBlockedSummary,
  outcome72hOperationsSummary,
  outcomeCaptureOperationsSummary,
  OUTCOME_72H_HELP,
  snapshotOperationsSummary,
} from "@/lib/operations-summaries";
import {
  formatCount,
  formatDateTimeLocal,
  formatRelativeTime,
  formatRuntimeSeconds,
} from "@/lib/operations-format";
import type {
  OperationsOverviewResponse,
  OutcomeAttributionMode,
} from "@/lib/operations-types";
import { cn } from "@/lib/utils";

const POLL_MS = 60_000;

function DailyBars({ daily }: { daily: { date: string; count: number }[] }) {
  const max = Math.max(1, ...daily.map((d) => d.count));
  return (
    <div className="flex items-end gap-1.5 pt-2 opacity-80">
      {daily.map((row) => (
        <div key={row.date} className="flex flex-1 flex-col items-center gap-1">
          <div
            className="w-full min-h-[4px] rounded-t bg-primary/40"
            style={{ height: `${Math.max(4, (row.count / max) * 48)}px` }}
            title={`${row.date}: ${row.count}`}
          />
          <span className="text-[10px] text-muted-foreground">{row.date.slice(5)}</span>
        </div>
      ))}
    </div>
  );
}

function MaturityStack({
  pending,
  valid,
  missing,
}: {
  pending: number;
  valid: number;
  missing: number;
}) {
  const total = pending + valid + missing;
  if (total <= 0) {
    return <p className="text-sm text-muted-foreground">Нет наблюдений для отображения.</p>;
  }
  const pct = (n: number) => `${Math.max(0, (n / total) * 100)}%`;
  return (
    <div className="space-y-2">
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-muted/60">
        {pending > 0 ? (
          <div
            className="bg-slate-500/60"
            style={{ width: pct(pending) }}
            title={`Ожидают 72 ч: ${pending}`}
          />
        ) : null}
        {valid > 0 ? (
          <div
            className="bg-emerald-600/50"
            style={{ width: pct(valid) }}
            title={`Исход измерен: ${valid}`}
          />
        ) : null}
        {missing > 0 ? (
          <div
            className="bg-muted-foreground/35"
            style={{ width: pct(missing) }}
            title={`Нет снимка на горизонте: ${missing}`}
          />
        ) : null}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>Ожидают 72 ч: {formatCount(pending)}</span>
        <span>Исход измерен: {formatCount(valid)}</span>
        <span>Нет подходящего снимка: {formatCount(missing)}</span>
      </div>
    </div>
  );
}

export function OperationsDashboard() {
  const [data, setData] = useState<OperationsOverviewResponse | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [initialError, setInitialError] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [livePlanner, setLivePlanner] = useState(false);
  const [attribution, setAttribution] = useState<OutcomeAttributionMode>("all_hits");

  const inFlight = useRef(false);
  const hasLoaded = useRef(false);

  const load = useCallback(
    async (background: boolean) => {
      if (inFlight.current) {
        return;
      }
      inFlight.current = true;
      if (!background) {
        if (!hasLoaded.current) {
          setInitialLoading(true);
        } else {
          setRefreshing(true);
        }
      } else {
        setRefreshing(true);
      }
      if (!background && !hasLoaded.current) {
        setInitialError(null);
      }
      try {
        const overview = await getOperationsOverview({
          include_live_monitoring_planner: livePlanner,
          outcome_attribution_mode: attribution,
        });
        setData(overview);
        setRefreshError(null);
        hasLoaded.current = true;
      } catch (err) {
        const message = err instanceof Error ? err.message : "Не удалось загрузить обзор операций";
        if (!hasLoaded.current) {
          setInitialError(message);
        } else {
          setRefreshError(message);
        }
      } finally {
        inFlight.current = false;
        setInitialLoading(false);
        setRefreshing(false);
      }
    },
    [attribution, livePlanner],
  );

  useEffect(() => {
    hasLoaded.current = false;
    setData(null);
    void load(false);
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") {
        return;
      }
      void load(true);
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  if (initialLoading && !data) {
    return (
      <PageShell>
        <Skeleton className="h-10 w-64" />
        <LoadingState variant="block" />
      </PageShell>
    );
  }

  if (initialError && !data) {
    return (
      <PageShell>
        <StateMessage variant="error" title="Не удалось загрузить операции" description={initialError} />
        <Button className="mt-4" onClick={() => void load(false)}>
          Повторить
        </Button>
      </PageShell>
    );
  }

  if (!data) {
    return (
      <PageShell>
        <StateMessage
          variant="empty"
          title="Данных пока нет"
          description="Циклы discovery и monitoring ещё не записаны в базу."
        />
      </PageShell>
    );
  }

  const {
    discovery,
    monitoring,
    outcome_capture: outcomeCapture,
    snapshots,
    keyword_outcomes: outcomes,
    errors,
    recent_cycles,
  } = data;
  const refIso = data.generated_at;
  const discoveryCycleRel = formatRelativeTime(discovery.last_cycle_finished_at, refIso).relative;
  const blocked = operationsBlockedSummary(discovery, monitoring, errors);

  const discoverySummary = discoveryOperationsSummary(discovery, discoveryCycleRel);
  const monitoringSummary = monitoringOperationsSummary(monitoring, snapshots.snapshots_last_24h);
  const snapshotSummary = snapshotOperationsSummary(snapshots);
  const outcomeSummary = outcome72hOperationsSummary(outcomes);
  const outcomeCaptureSummary = outcomeCaptureOperationsSummary(outcomeCapture);

  const hasErrors =
    Boolean(errors.discovery_last_cycle_error) || errors.monitoring_recent_error_summaries.length > 0;

  return (
    <PageShell>
      <PageHeader
        icon={<Activity className="h-6 w-6 text-primary" aria-hidden />}
        title="Операции"
        lead="Работают ли discovery, monitoring и накопление снимков. Не оценка качества ключей или видео."
        actions={
          <Button
            variant="outline"
            size="sm"
            disabled={refreshing}
            onClick={() => void load(true)}
            data-testid="operations-refresh"
          >
            <RefreshCw className={cn("mr-2 h-4 w-4", refreshing && "animate-spin")} aria-hidden />
            Обновить
          </Button>
        }
      />

      <RefreshingIndicator visible={refreshing} />

      {refreshError ? (
        <StaleDataWarning
          message={`Ошибка обновления: ${refreshError}. Показаны последние успешные данные.`}
          generatedAtLabel={formatDateTimeLocal(data.generated_at)}
        />
      ) : null}

      <div className="space-y-3" data-testid="operations-summary-layer">
        {blocked ? (
          <SummaryStrip tone={blocked.tone} lines={blocked.lines} data-testid="operations-blocked-summary" />
        ) : null}
        <SummaryStrip
          tone={discoverySummary.tone}
          lines={discoverySummary.lines}
          data-testid="operations-discovery-summary"
        />
        <SummaryStrip
          tone={monitoringSummary.tone}
          lines={monitoringSummary.lines}
          data-testid="operations-monitoring-summary"
        />
        <SummaryStrip
          tone={outcomeCaptureSummary.tone}
          lines={outcomeCaptureSummary.lines}
          data-testid="operations-outcome-capture-summary"
        />
        <SummaryStrip
          tone={snapshotSummary.tone}
          lines={snapshotSummary.lines}
          data-testid="operations-snapshot-summary"
        />
        <SummaryStrip
          tone={outcomeSummary.tone}
          lines={outcomeSummary.lines}
          data-testid="operations-outcome-summary"
        />
      </div>

      <SectionPanel title="Discovery">
        <SystemStatusBadge state={discovery.worker.activity_state} />
        <MetricGroup>
          <Metric
            label="Ключей пора обработать"
            value={formatCount(discovery.keywords_due_now)}
            testId="operations-discovery-due-now"
            tooltip={METRIC_TOOLTIPS.dueKeyword}
          />
          <Metric label="В ближайший 1 ч" value={formatCount(discovery.keywords_due_next_1h)} />
          <Metric label="В ближайшие 24 ч" value={formatCount(discovery.keywords_due_next_24h)} />
          <Metric
            label="Найдено видео в последнем цикле"
            value={formatCount(discovery.unique_videos_last_cycle)}
          />
          <Metric
            label="Сохранено видео"
            value={formatCount(discovery.persisted_videos_last_cycle)}
          />
        </MetricGroup>
        <Disclosure summary="Технические детали последнего цикла">
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-muted-foreground">Сырьевые кандидаты (raw)</dt>
              <dd className="tabular-nums">{formatCount(discovery.raw_candidates_last_cycle)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Длительность</dt>
              <dd>{formatRuntimeSeconds(discovery.last_cycle_runtime_seconds)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Run ID</dt>
              <dd className="font-mono text-xs">{discovery.last_run_id ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Ошибки ключей</dt>
              <dd>{formatCount(discovery.keyword_errors_last_cycle)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Начало цикла</dt>
              <dd>{formatDateTimeLocal(discovery.last_cycle_started_at)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Завершение цикла</dt>
              <dd>{formatDateTimeLocal(discovery.last_cycle_finished_at)}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-muted-foreground">Lock / воркер</dt>
              <dd className="text-xs text-muted-foreground">{discovery.worker.liveness_note}</dd>
            </div>
          </dl>
        </Disclosure>
      </SectionPanel>

      <SectionPanel title="Monitoring">
        <div className="flex flex-wrap items-center gap-2">
          <SystemStatusBadge state={monitoring.worker.activity_state} />
        </div>
        {monitoring.loaded_video_count > 0 && monitoring.eligible_video_count === 0 ? (
          <div data-testid="operations-monitoring-no-eligible">
            <ZeroContextNote>
              Видео в базе есть, но сейчас нет видео, подходящих под текущие правила мониторинга.
            </ZeroContextNote>
          </div>
        ) : null}
        <MetricGroup>
          <Metric label="Проверено видео" value={formatCount(monitoring.loaded_video_count)} />
          <Metric label="Подходит для наблюдения" value={formatCount(monitoring.eligible_video_count)} />
          <Metric label="Выбрано для снимка" value={formatCount(monitoring.selected_capture_count)} />
          <Metric label="Снимков сохранено" value={formatCount(monitoring.inserted_snapshot_count)} />
          <Metric
            label="Пора обработать"
            value={formatCount(monitoring.due_count_at_last_cycle)}
            testId="operations-monitoring-due"
            tooltip={METRIC_TOOLTIPS.dueCheckpoint}
          />
          <Metric
            label="Просрочено"
            value={formatCount(monitoring.overdue_count_at_last_cycle)}
            testId="operations-monitoring-overdue"
            tooltip={METRIC_TOOLTIPS.overdue}
          />
        </MetricGroup>
        <div className={cn(surfaces.sectionMuted, "mt-2 space-y-2 p-3")}>
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={livePlanner}
              onChange={(e) => setLivePlanner(e.target.checked)}
              data-testid="operations-live-planner-toggle"
            />
            Актуальные due/overdue
            <InfoTooltip content="Требует более тяжёлого запроса к API." />
          </label>
          {livePlanner && monitoring.live_planner_due_count != null ? (
            <p className="text-xs text-muted-foreground">
              Сейчас по планировщику: пора {formatCount(monitoring.live_planner_due_count)}, просрочено{" "}
              {formatCount(monitoring.live_planner_overdue_count ?? 0)}
            </p>
          ) : null}
        </div>
        <Disclosure summary="Счётчики сбоев и детали цикла">
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-muted-foreground">Не найдено (missing)</dt>
              <dd>{formatCount(monitoring.missing_count)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Ошибки загрузки</dt>
              <dd>{formatCount(monitoring.fetch_failed_count)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Ошибки валидации</dt>
              <dd>{formatCount(monitoring.validation_failed_count)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Ошибки сохранения</dt>
              <dd>{formatCount(monitoring.persistence_failed_count)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Длительность</dt>
              <dd>{formatRuntimeSeconds(monitoring.last_cycle_runtime_seconds)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Run ID</dt>
              <dd className="font-mono text-xs">{monitoring.last_run_id ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Начало</dt>
              <dd>{formatDateTimeLocal(monitoring.last_cycle_started_at)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Завершение</dt>
              <dd>{formatDateTimeLocal(monitoring.last_cycle_finished_at)}</dd>
            </div>
          </dl>
        </Disclosure>
      </SectionPanel>

      <div className="grid gap-8 lg:grid-cols-2">
        <SectionPanel title="Снимки">
          {snapshots.snapshots_last_24h === 0 ? (
            <div data-testid="operations-snapshot-zero-24h">
              <ZeroContextNote>За последние 24 ч новые снимки не создавались.</ZeroContextNote>
            </div>
          ) : null}
          <MetricGroup>
            <Metric label="За последний час" value={formatCount(snapshots.snapshots_last_1h)} />
            <Metric
              label="За 24 ч"
              value={formatCount(snapshots.snapshots_last_24h)}
              testId="operations-snapshot-24h"
            />
            <Metric
              label="Уникальных видео за 24 ч"
              value={formatCount(snapshots.unique_videos_snapshotted_last_24h)}
            />
            <Metric
              label="Последний снимок"
              value={formatRelativeTime(snapshots.latest_snapshot_at, refIso).relative}
              helper={formatDateTimeLocal(snapshots.latest_snapshot_at)}
            />
          </MetricGroup>
          {snapshots.daily_counts_last_7d.length > 0 ? (
            <div className="mt-2">
              <p className="text-xs text-muted-foreground">Снимки по дням (UTC), 7 дней</p>
              <DailyBars daily={snapshots.daily_counts_last_7d} />
            </div>
          ) : null}
        </SectionPanel>

        <SectionPanel title="72 ч исходы">
          <p className="text-sm text-muted-foreground">{OUTCOME_72H_HELP}</p>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              Атрибуция:
              <select
                className="h-8 rounded-md border border-input bg-background/50 px-2 text-sm text-foreground"
                value={attribution}
                onChange={(e) => setAttribution(e.target.value as OutcomeAttributionMode)}
                aria-label="Режим атрибуции 72 ч"
                data-testid="operations-attribution-select"
              >
                <option value="all_hits">Все находки</option>
                <option value="first_discovery">Первый источник</option>
              </select>
              <InfoTooltip content={METRIC_TOOLTIPS.attribution} />
            </label>
          </div>
          {outcomes.valid_72h_outcome_count === 0 ? (
            <div data-testid="operations-outcome-zero-valid">
              <ZeroContextNote>Валидных 72 ч исходов пока нет.</ZeroContextNote>
            </div>
          ) : null}
          <MaturityStack
            pending={outcomes.pending_72h_count}
            valid={outcomes.valid_72h_outcome_count}
            missing={outcomes.missing_72h_outcome_count}
          />
          <MetricGroup>
            <Metric label="Всего наблюдений" value={formatCount(outcomes.attributed_observation_count)} />
            <Metric label="Ожидают 72 ч" value={formatCount(outcomes.pending_72h_count)} testId="operations-outcome-pending" />
            <Metric label="Созрело" value={formatCount(outcomes.matured_72h_count)} />
            <Metric
              label="Исход измерен"
              value={formatCount(outcomes.valid_72h_outcome_count)}
              testId="operations-outcome-valid"
            />
            <Metric
              label="Нет подходящего снимка"
              value={formatCount(outcomes.missing_72h_outcome_count)}
              testId="operations-outcome-missing"
            />
            <Metric label="Дозреет через 6 ч" value={formatCount(outcomes.matures_next_6h)} testId="operations-upcoming-6h" />
            <Metric label="Дозреет через 24 ч" value={formatCount(outcomes.matures_next_24h)} testId="operations-upcoming-24h" />
            <Metric label="Дозреет через 48 ч" value={formatCount(outcomes.matures_next_48h)} testId="operations-upcoming-48h" />
          </MetricGroup>
          {attribution === "first_discovery" ? (
            <p className="text-xs text-muted-foreground">
              Первый источник: видео засчитывается ключу с самым ранним обнаружением; при равном времени — меньший
              keyword_id.
            </p>
          ) : null}
        </SectionPanel>
      </div>

      {hasErrors ? (
        <section className="space-y-3" data-testid="operations-errors-section">
          <SummaryStrip
            tone="error"
            lines={[{ text: "В последних циклах зафиксированы ошибки.", emphasis: true }]}
          />
          <Disclosure summary="Технические детали ошибок" defaultOpen>
            <div className="space-y-2 text-sm">
              {errors.discovery_last_cycle_error ? (
                <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-3">
                  Discovery: {errors.discovery_last_cycle_error}
                </p>
              ) : null}
              {errors.monitoring_recent_error_summaries.map((msg) => (
                <p key={msg} className="rounded-lg border border-destructive/30 bg-destructive/5 p-3">
                  Monitoring: {msg}
                </p>
              ))}
            </div>
          </Disclosure>
        </section>
      ) : null}

      <SectionPanel title="Циклы discovery">
        <div data-testid="operations-discovery-cycles">
          <DiscoveryCyclesTable rows={recent_cycles.discovery} refIso={refIso} />
        </div>
      </SectionPanel>

      <SectionPanel title="Циклы monitoring">
        <div data-testid="operations-monitoring-cycles">
          <MonitoringCyclesTable rows={recent_cycles.monitoring} refIso={refIso} />
        </div>
      </SectionPanel>

      <p className="text-center text-xs text-muted-foreground" data-testid="operations-liveness-note">
        Срез API: {formatDateTimeLocal(data.generated_at)}
        {discovery.worker.liveness_note ? ` · ${LIVENESS_DISCLAIMER}` : null}
      </p>
    </PageShell>
  );
}
