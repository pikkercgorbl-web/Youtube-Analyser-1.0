"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { CalendarDays } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  PageShell,
  SectionPanel,
  ZeroContextNote,
} from "@/components/design-system";
import {
  getDailyIntelligenceOutcomeCoverage,
  getDailyIntelligenceReport,
  listDailyIntelligenceDates,
  listDailyIntelligenceFamilies,
  listDailyIntelligenceRuns,
  listDailyIntelligenceWinners,
} from "@/lib/api";
import type { DailyIntelligenceOutcomeCoverageResponse } from "@/lib/daily-intelligence-outcome-types";
import { dailyIntelligenceStatusHint } from "@/lib/daily-intelligence-labels";
import type {
  DailyIntelligenceFamilyListItem,
  DailyIntelligenceReportSummary,
  DailyIntelligenceRunSnapshotItem,
  DailyIntelligenceWinnerListItem,
} from "@/lib/daily-intelligence-types";
import { formatDateTimeLocal } from "@/lib/monitoring-format";
import { cn } from "@/lib/utils";

import { dailyIntelligenceFamilyDetailHref } from "@/lib/daily-intelligence-routes";

import { DailyIntelligenceOutcomeCoverageSummary } from "./daily-intelligence-outcome-coverage-summary";
import { DailyIntelligencePagination } from "./daily-intelligence-pagination";
import { DailyIntelligenceStatusBadge } from "./daily-intelligence-status-badge";
import { DailyIntelligenceWinnerRow } from "./daily-intelligence-winner-row";

const PAGE_SIZE = 25;
const DATES_FETCH_LIMIT = 200;

type Paginated<T> = {
  items: T[];
  total: number;
  offset: number;
  loading: boolean;
  error: string | null;
};

function emptyPaginated<T>(): Paginated<T> {
  return { items: [], total: 0, offset: 0, loading: false, error: null };
}

export function DailyIntelligenceDashboard() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const dateFromUrl = searchParams.get("date");

  const [datesLoading, setDatesLoading] = useState(true);
  const [datesError, setDatesError] = useState<string | null>(null);
  const [availableDates, setAvailableDates] = useState<string[]>([]);

  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [report, setReport] = useState<DailyIntelligenceReportSummary | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  const [winners, setWinners] = useState<Paginated<DailyIntelligenceWinnerListItem>>(emptyPaginated());
  const [families, setFamilies] = useState<Paginated<DailyIntelligenceFamilyListItem>>(emptyPaginated());
  const [runs, setRuns] = useState<Paginated<DailyIntelligenceRunSnapshotItem>>(emptyPaginated());

  const [outcomeCoverage, setOutcomeCoverage] = useState<DailyIntelligenceOutcomeCoverageResponse | null>(
    null,
  );
  const [outcomeCoverageLoading, setOutcomeCoverageLoading] = useState(false);
  const [outcomeCoverageError, setOutcomeCoverageError] = useState<string | null>(null);

  const setDateInUrl = useCallback(
    (date: string) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("date", date);
      router.replace(`/daily-intelligence?${params.toString()}`, { scroll: false });
    },
    [router, searchParams],
  );

  const loadDates = useCallback(async () => {
    setDatesLoading(true);
    setDatesError(null);
    try {
      const res = await listDailyIntelligenceDates({ limit: DATES_FETCH_LIMIT, offset: 0 });
      const sorted = res.items.map((x) => x.report_date).sort((a, b) => b.localeCompare(a));
      setAvailableDates(sorted);
      if (sorted.length === 0) {
        setSelectedDate(null);
        return;
      }
      const pick =
        dateFromUrl && sorted.includes(dateFromUrl) ? dateFromUrl : sorted[0]!;
      setSelectedDate(pick);
      if (pick !== dateFromUrl) {
        setDateInUrl(pick);
      }
    } catch (err) {
      setDatesError(err instanceof Error ? err.message : "Не удалось загрузить даты");
    } finally {
      setDatesLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- initial fetch + explicit retry only
  }, []);

  useEffect(() => {
    void loadDates();
  }, [loadDates]);

  useEffect(() => {
    if (!dateFromUrl || availableDates.length === 0) {
      return;
    }
    if (availableDates.includes(dateFromUrl)) {
      setSelectedDate(dateFromUrl);
    }
  }, [dateFromUrl, availableDates]);

  const loadReport = useCallback(async (reportDate: string) => {
    setReportLoading(true);
    setReportError(null);
    try {
      const summary = await getDailyIntelligenceReport(reportDate);
      setReport(summary);
    } catch (err) {
      setReport(null);
      setReportError(err instanceof Error ? err.message : "Не удалось загрузить отчёт");
    } finally {
      setReportLoading(false);
    }
  }, []);

  const loadWinners = useCallback(async (reportDate: string, offset: number) => {
    setWinners((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const res = await listDailyIntelligenceWinners(reportDate, { limit: PAGE_SIZE, offset });
      setWinners({ items: res.items, total: res.total, offset: res.offset, loading: false, error: null });
    } catch (err) {
      setWinners((prev) => ({
        ...prev,
        loading: false,
        error: err instanceof Error ? err.message : "Ошибка загрузки winners",
      }));
    }
  }, []);

  const loadFamilies = useCallback(async (reportDate: string, offset: number) => {
    setFamilies((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const res = await listDailyIntelligenceFamilies(reportDate, { limit: PAGE_SIZE, offset });
      setFamilies({ items: res.items, total: res.total, offset: res.offset, loading: false, error: null });
    } catch (err) {
      setFamilies((prev) => ({
        ...prev,
        loading: false,
        error: err instanceof Error ? err.message : "Ошибка загрузки families",
      }));
    }
  }, []);

  const loadOutcomeCoverage = useCallback(async (reportDate: string) => {
    setOutcomeCoverageLoading(true);
    setOutcomeCoverageError(null);
    try {
      const res = await getDailyIntelligenceOutcomeCoverage(reportDate);
      setOutcomeCoverage(res);
    } catch (err) {
      setOutcomeCoverageError(err instanceof Error ? err.message : "Ошибка outcome coverage");
    } finally {
      setOutcomeCoverageLoading(false);
    }
  }, []);

  const loadRuns = useCallback(async (reportDate: string, offset: number) => {
    setRuns((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const res = await listDailyIntelligenceRuns(reportDate, { limit: PAGE_SIZE, offset });
      setRuns({ items: res.items, total: res.total, offset: res.offset, loading: false, error: null });
    } catch (err) {
      setRuns((prev) => ({
        ...prev,
        loading: false,
        error: err instanceof Error ? err.message : "Ошибка загрузки runs",
      }));
    }
  }, []);

  useEffect(() => {
    if (!selectedDate) {
      return;
    }
    void loadReport(selectedDate);
    void loadWinners(selectedDate, 0);
    void loadFamilies(selectedDate, 0);
    void loadRuns(selectedDate, 0);
    void loadOutcomeCoverage(selectedDate);
  }, [selectedDate, loadReport, loadWinners, loadFamilies, loadRuns, loadOutcomeCoverage]);

  const outcomeCoverageByVideoId = useMemo(() => {
    const map = new Map<
      string,
      { coverage_category: string; outcome_window_phase: string }
    >();
    if (!outcomeCoverage?.items) {
      return map;
    }
    for (const item of outcomeCoverage.items) {
      map.set(item.video_id, {
        coverage_category: item.coverage_category,
        outcome_window_phase: item.outcome_window_phase,
      });
    }
    return map;
  }, [outcomeCoverage]);

  const onSelectDate = (value: string) => {
    setSelectedDate(value);
    setDateInUrl(value);
  };

  const headerMeta = useMemo(() => {
    if (!report) {
      return null;
    }
    return (
      <div className="rounded-xl border border-border bg-card/40 p-4 space-y-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-muted-foreground">UTC-день:</span>
          <span className="font-medium tabular-nums">{report.report_date}</span>
          <DailyIntelligenceStatusBadge
            status={report.status}
            title={dailyIntelligenceStatusHint(report.status) ?? undefined}
          />
        </div>
        {dailyIntelligenceStatusHint(report.status) ? (
          <p className="text-xs text-muted-foreground">{dailyIntelligenceStatusHint(report.status)}</p>
        ) : null}
        <dl className="grid gap-2 sm:grid-cols-2 text-xs">
          <div>
            <dt className="text-muted-foreground">source_run_id</dt>
            <dd className="font-mono break-all">{report.source_run_id ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">source_computed_at (UTC)</dt>
            <dd>{formatDateTimeLocal(report.source_computed_at)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Окно Attention</dt>
            <dd>
              {formatDateTimeLocal(report.source_window_start)} →{" "}
              {formatDateTimeLocal(report.source_window_end)}
              {report.source_window_hours != null ? ` (${report.source_window_hours} ч)` : ""}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Winners / Families (итого)</dt>
            <dd className="tabular-nums">
              {report.winner_count ?? "—"} / {report.family_count ?? "—"}
            </dd>
          </div>
          {report.locked_at ? (
            <div>
              <dt className="text-muted-foreground">locked_at (UTC)</dt>
              <dd>{formatDateTimeLocal(report.locked_at)}</dd>
            </div>
          ) : null}
        </dl>
        {report.coverage_gaps?.length ? (
          <ZeroContextNote>
            Ограничения покрытия: {report.coverage_gaps.join("; ")}
          </ZeroContextNote>
        ) : null}
      </div>
    );
  }, [report]);

  if (datesLoading) {
    return (
      <PageShell>
        <LoadingState title="Загрузка архива…" />
      </PageShell>
    );
  }

  if (datesError) {
    return (
      <PageShell>
        <ErrorState title="Ошибка загрузки дат" description={datesError} onRetry={() => void loadDates()} />
      </PageShell>
    );
  }

  if (availableDates.length === 0) {
    return (
      <PageShell>
        <PageHeader
          icon={<CalendarDays className="h-7 w-7 text-primary" />}
          title="Архив Daily Intelligence"
          lead="Исторические снимки Attention (замороженные данные, не текущий snapshot)."
        />
        <EmptyState
          title="Исторических отчётов пока нет"
          description="Архив заполняется при каждой успешной публикации Attention Engine."
        />
      </PageShell>
    );
  }

  return (
    <PageShell>
      <PageHeader
        icon={<CalendarDays className="h-7 w-7 text-primary" />}
        title="Архив Daily Intelligence"
        lead="Замороженные Winners и Pattern Families на момент публикации Attention за выбранный UTC-день."
      />

      <SectionPanel title="Выбор даты" description="Только даты, для которых есть запись в архиве.">
        <label className="block max-w-md text-sm">
          <span className="text-muted-foreground">report_date (UTC)</span>
          <select
            className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            value={selectedDate ?? ""}
            onChange={(e) => onSelectDate(e.target.value)}
          >
            {availableDates.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
      </SectionPanel>

      {reportLoading && !report ? <LoadingState title="Загрузка отчёта…" variant="inline" /> : null}
      {reportError ? (
        <ErrorState title="Отчёт недоступен" description={reportError} compact onRetry={() => selectedDate && void loadReport(selectedDate)} />
      ) : null}
      {headerMeta}

      {selectedDate && report?.status === "unavailable" ? (
        <ZeroContextNote>
          За этот UTC-день нет сохранённой публикации Attention. Списки Winners/Families могут быть пустыми.
        </ZeroContextNote>
      ) : null}

      <SectionPanel
        title="Historical Outcome Follow-up"
        description="Покрытие 72h outcome для winners выбранного UTC-дня (один запрос на день, без N+1)."
      >
        <DailyIntelligenceOutcomeCoverageSummary
          data={outcomeCoverage}
          loading={outcomeCoverageLoading}
          error={outcomeCoverageError}
          onRetry={() => selectedDate && void loadOutcomeCoverage(selectedDate)}
        />
      </SectionPanel>

      <SectionPanel
        title="Daily Winners"
        description={`Всего в архиве за день: ${winners.total}. Данные из frozen daily edition, не live Attention.`}
      >
        {winners.error ? (
          <ErrorState title={winners.error} compact onRetry={() => void loadWinners(selectedDate!, winners.offset)} />
        ) : winners.loading && winners.items.length === 0 ? (
          <LoadingState variant="table" rows={5} />
        ) : winners.total === 0 ? (
          <EmptyState title="Нет winners" compact />
        ) : (
          <>
            <div className="overflow-x-auto rounded-xl border border-border">
              <table className="w-full text-sm">
                <thead className="bg-muted/30 text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 w-12">#</th>
                    <th className="px-3 py-2">Видео</th>
                    <th className="px-3 py-2">Канал</th>
                    <th className="px-3 py-2 w-28">Provenance</th>
                    <th className="px-3 py-2 w-24">Повтор</th>
                    <th className="px-3 py-2 min-w-[100px]">Outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {winners.items.map((row) => (
                    <DailyIntelligenceWinnerRow
                      key={row.video_id}
                      row={row}
                      reportDate={selectedDate!}
                      outcomeCoverage={outcomeCoverageByVideoId.get(row.video_id)}
                      outcomeCoveragePending={outcomeCoverageLoading && !outcomeCoverage}
                    />
                  ))}
                </tbody>
              </table>
            </div>
            <DailyIntelligencePagination
              total={winners.total}
              offset={winners.offset}
              limit={PAGE_SIZE}
              disabled={winners.loading}
              onPageChange={(o) => void loadWinners(selectedDate!, o)}
            />
          </>
        )}
      </SectionPanel>

      <SectionPanel
        title="Pattern Families"
        description={`Всего: ${families.total}. Счётчики — снимок на момент публикации, не прогноз успеха.`}
      >
        {families.error ? (
          <ErrorState title={families.error} compact onRetry={() => void loadFamilies(selectedDate!, families.offset)} />
        ) : families.loading && families.items.length === 0 ? (
          <LoadingState variant="table" rows={4} />
        ) : families.total === 0 ? (
          <EmptyState title="Нет families" compact />
        ) : (
          <>
            <ul className="space-y-2">
              {families.items.map((row) => (
                <li key={row.family_key} className="rounded-xl border border-border px-3 py-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="font-medium line-clamp-2 break-words">
                        <span className="text-muted-foreground tabular-nums mr-2">#{row.rank}</span>
                        <Link
                          href={dailyIntelligenceFamilyDetailHref(selectedDate!, row.family_key)}
                          className="hover:text-primary"
                          data-testid="di-family-detail-link"
                        >
                          {row.label}
                        </Link>
                      </p>
                      <p className="text-xs text-muted-foreground font-mono break-all mt-1">{row.family_key}</p>
                    </div>
                    <span className="text-xs text-muted-foreground shrink-0">
                      {row.is_repeat_in_prior_reports ? "Повтор" : "Новая в архиве"}
                    </span>
                  </div>
                  <p className="mt-2 text-sm tabular-nums text-muted-foreground">
                    видео: {row.video_count ?? "—"} · каналы: {row.channel_count ?? "—"}
                  </p>
                </li>
              ))}
            </ul>
            <DailyIntelligencePagination
              total={families.total}
              offset={families.offset}
              limit={PAGE_SIZE}
              disabled={families.loading}
              onPageChange={(o) => void loadFamilies(selectedDate!, o)}
            />
          </>
        )}
      </SectionPanel>

      <SectionPanel
        title="Run History"
        description={`Публикации Attention внутри UTC-дня ${selectedDate}. Всего запусков: ${runs.total}.`}
      >
        {runs.error ? (
          <ErrorState title={runs.error} compact onRetry={() => void loadRuns(selectedDate!, runs.offset)} />
        ) : runs.loading && runs.items.length === 0 ? (
          <LoadingState variant="table" rows={3} />
        ) : runs.total === 0 ? (
          <EmptyState title="Нет записей о запусках" compact />
        ) : (
          <>
            <ul className="space-y-2 text-sm">
              {runs.items.map((row) => (
                <li key={row.source_run_id} className="rounded-lg border border-border/80 px-3 py-2">
                  <p className="font-mono text-xs break-all">{row.source_run_id}</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    {formatDateTimeLocal(row.source_computed_at)} UTC · winners {row.winner_count} · families{" "}
                    {row.family_count}
                  </p>
                </li>
              ))}
            </ul>
            <DailyIntelligencePagination
              total={runs.total}
              offset={runs.offset}
              limit={PAGE_SIZE}
              disabled={runs.loading}
              onPageChange={(o) => void loadRuns(selectedDate!, o)}
            />
          </>
        )}
      </SectionPanel>

      <p className="text-xs text-muted-foreground">
        Текущий раздел{" "}
        <Link href="/opportunities" className="text-primary hover:underline">
          Возможности
        </Link>{" "}
        показывает live Attention — здесь только архив.
      </p>
    </PageShell>
  );
}
