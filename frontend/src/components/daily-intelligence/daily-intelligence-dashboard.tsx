"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { CalendarDays } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import {
  Disclosure,
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
import type {
  DailyIntelligenceFamilyListItem,
  DailyIntelligenceReportSummary,
  DailyIntelligenceRunSnapshotItem,
  DailyIntelligenceWinnerListItem,
} from "@/lib/daily-intelligence-types";
import { cn } from "@/lib/utils";

import { dailyIntelligenceFamilyDetailHref } from "@/lib/daily-intelligence-routes";

import { DailyIntelligenceOutcomeCoverageSummary } from "./daily-intelligence-outcome-coverage-summary";
import { DailyIntelligencePagination } from "./daily-intelligence-pagination";
import { DailyIntelligenceReportHeader } from "./daily-intelligence-report-header";
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

  const onSelectDate = (value: string) => {
    setSelectedDate(value);
    setDateInUrl(value);
  };

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

      <SectionPanel title="Выбор даты" description="Дни, для которых сохранён архивный выпуск.">
        <label className="block max-w-md text-sm">
          <span className="text-muted-foreground">Дата отчёта (UTC)</span>
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
      {report ? <DailyIntelligenceReportHeader report={report} /> : null}

      {selectedDate && report?.status === "unavailable" ? (
        <ZeroContextNote>
          За этот UTC-день нет сохранённой публикации Attention. Списки Winners/Families могут быть пустыми.
        </ZeroContextNote>
      ) : null}

      <SectionPanel
        title="Видео, на которые стоит посмотреть"
        description={`В выпуске: ${winners.total} видео. Метрики — снимок Attention при публикации, не сегодняшние.`}
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
                    <th className="px-3 py-2">Видео</th>
                    <th className="px-3 py-2">Причина в отчёте</th>
                    <th className="px-3 py-2 w-28">Место</th>
                    <th className="px-3 py-2 w-32">Действие</th>
                  </tr>
                </thead>
                <tbody>
                  {winners.items.map((row) => (
                    <DailyIntelligenceWinnerRow
                      key={row.video_id}
                      row={row}
                      reportDate={selectedDate!}
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
        title="Темы и подборки"
        description={`В выпуске: ${families.total} тем. Это группировки pattern families на момент публикации, не прогноз.`}
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

      {report ? (
        <section className="rounded-xl border border-border/60 p-4">
          <Disclosure summary="Данные и расчёт">
            <div className="space-y-6 text-sm">
              <dl className="grid gap-2 sm:grid-cols-2 text-xs font-mono break-all">
                <div>
                  <dt className="text-muted-foreground font-sans">source_run_id</dt>
                  <dd>{report.source_run_id ?? "—"}</dd>
                </div>
                {report.locked_at ? (
                  <div>
                    <dt className="text-muted-foreground font-sans">locked_at</dt>
                    <dd>{report.locked_at}</dd>
                  </div>
                ) : null}
                <div>
                  <dt className="text-muted-foreground font-sans">publish_attempt</dt>
                  <dd>{report.publish_attempt}</dd>
                </div>
              </dl>
              <DailyIntelligenceOutcomeCoverageSummary
                data={outcomeCoverage}
                loading={outcomeCoverageLoading}
                error={outcomeCoverageError}
                onRetry={() => selectedDate && void loadOutcomeCoverage(selectedDate)}
              />
              <div>
                <p className="font-medium mb-2">Run history ({runs.total})</p>
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
                            {row.source_computed_at} · winners {row.winner_count} · families {row.family_count}
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
              </div>
            </div>
          </Disclosure>
        </section>
      ) : null}

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
