"use client";

import { Fragment } from "react";

import {
  DataTableHead,
  DataTableRow,
  DataTableShell,
  DataTableTd,
  DataTableTh,
  ExpandableTableRow,
} from "@/components/design-system";
import { CycleStatusBadge } from "@/components/design-system/status-badges";
import { textRoles } from "@/lib/design-system/typography";
import {
  formatCount,
  formatDateTimeLocal,
  formatRelativeTime,
  formatRuntimeSeconds,
} from "@/lib/operations-format";
import type { DiscoveryCycleOps, MonitoringCycleHistoryItem } from "@/lib/operations-types";
import { cn } from "@/lib/utils";

function discoveryCycleStatus(row: DiscoveryCycleOps): string {
  if (row.error_summaries.length > 0 || row.keyword_scan_failures > 0) {
    return "partial";
  }
  return "ok";
}

export function DiscoveryCyclesTable({
  rows,
  refIso,
}: {
  rows: DiscoveryCycleOps[];
  refIso: string | null;
}) {
  const colSpan = 5;

  return (
    <DataTableShell minWidthClassName="min-w-[520px]" className="text-sm">
      <DataTableHead>
        <tr>
          <DataTableTh>Время</DataTableTh>
          <DataTableTh>Статус</DataTableTh>
          <DataTableTh align="right">Ключей</DataTableTh>
          <DataTableTh align="right">Уникальных видео</DataTableTh>
          <DataTableTh align="right">Сохранено</DataTableTh>
        </tr>
      </DataTableHead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td colSpan={colSpan} className="px-3 py-6 text-center text-muted-foreground">
              Нет записанных циклов
            </td>
          </tr>
        ) : (
          rows.map((row) => (
            <Fragment key={row.discovery_run_id}>
              <DataTableRow>
                <DataTableTd emphasis>
                  <span title={formatDateTimeLocal(row.finished_at)}>
                    {formatRelativeTime(row.finished_at, refIso).relative}
                  </span>
                </DataTableTd>
                <DataTableTd>
                  <CycleStatusBadge status={discoveryCycleStatus(row)} />
                </DataTableTd>
                <DataTableTd align="right">{formatCount(row.keywords_scanned)}</DataTableTd>
                <DataTableTd align="right">{formatCount(row.unique_candidates)}</DataTableTd>
                <DataTableTd align="right">{formatCount(row.persisted_videos)}</DataTableTd>
              </DataTableRow>
              <ExpandableTableRow colSpan={colSpan} summary="Технические детали">
                <dl className={cn(textRoles.metadata, "grid gap-2 sm:grid-cols-2")}>
                  <div>
                    <dt className="text-muted-foreground">Run ID</dt>
                    <dd className={textRoles.code}>{row.discovery_run_id}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Сырьевые кандидаты (raw)</dt>
                    <dd>{formatCount(row.raw_candidates)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Длительность</dt>
                    <dd>{formatRuntimeSeconds(row.runtime_seconds)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Ошибки ключей</dt>
                    <dd>{formatCount(row.keyword_scan_failures)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Начало</dt>
                    <dd>{formatDateTimeLocal(row.started_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Завершение</dt>
                    <dd>{formatDateTimeLocal(row.finished_at)}</dd>
                  </div>
                  {row.error_summaries.length > 0 ? (
                    <div className="sm:col-span-2">
                      <dt className="text-muted-foreground">Сообщения об ошибках</dt>
                      <dd className="mt-1 space-y-1">
                        {row.error_summaries.map((msg) => (
                          <p key={msg} className="rounded border border-border/50 bg-muted/20 px-2 py-1">
                            {msg}
                          </p>
                        ))}
                      </dd>
                    </div>
                  ) : null}
                </dl>
              </ExpandableTableRow>
            </Fragment>
          ))
        )}
      </tbody>
    </DataTableShell>
  );
}

export function MonitoringCyclesTable({
  rows,
  refIso,
}: {
  rows: MonitoringCycleHistoryItem[];
  refIso: string | null;
}) {
  const colSpan = 5;

  return (
    <DataTableShell minWidthClassName="min-w-[520px]" className="text-sm">
      <DataTableHead>
        <tr>
          <DataTableTh>Время</DataTableTh>
          <DataTableTh>Статус</DataTableTh>
          <DataTableTh align="right">Выбрано</DataTableTh>
          <DataTableTh align="right">Снимков сохранено</DataTableTh>
          <DataTableTh align="right">Пора / просрочено</DataTableTh>
        </tr>
      </DataTableHead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td colSpan={colSpan} className="px-3 py-6 text-center text-muted-foreground">
              Нет записанных циклов
            </td>
          </tr>
        ) : (
          rows.map((row) => {
            const failures =
              row.fetch_failed_count + row.validation_failed_count + row.persistence_failed_count;
            return (
              <Fragment key={row.run_id}>
                <DataTableRow>
                  <DataTableTd emphasis>
                    <span title={formatDateTimeLocal(row.finished_at ?? row.started_at)}>
                      {formatRelativeTime(row.finished_at ?? row.started_at, refIso).relative}
                    </span>
                  </DataTableTd>
                  <DataTableTd>
                    <CycleStatusBadge status={row.cycle_status} showRawInTitle />
                  </DataTableTd>
                  <DataTableTd align="right">{formatCount(row.selected_request_count)}</DataTableTd>
                  <DataTableTd align="right">{formatCount(row.inserted_snapshot_count)}</DataTableTd>
                  <DataTableTd align="right" muted>
                    {formatCount(row.due_count)} / {formatCount(row.overdue_count)}
                  </DataTableTd>
                </DataTableRow>
                <ExpandableTableRow colSpan={colSpan} summary="Технические детали">
                  <dl className={cn(textRoles.metadata, "grid gap-2 sm:grid-cols-2")}>
                    <div>
                      <dt className="text-muted-foreground">Run ID</dt>
                      <dd className={textRoles.code}>{row.run_id}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">Загружено видео (loaded)</dt>
                      <dd>{formatCount(row.loaded_video_count)}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">Не найдено (missing)</dt>
                      <dd>{formatCount(row.missing_count)}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">Длительность</dt>
                      <dd>{formatRuntimeSeconds(row.runtime_seconds)}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">Ошибки загрузки</dt>
                      <dd>{formatCount(row.fetch_failed_count)}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">Ошибки валидации</dt>
                      <dd>{formatCount(row.validation_failed_count)}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">Ошибки сохранения</dt>
                      <dd>{formatCount(row.persistence_failed_count)}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">Всего сбоев</dt>
                      <dd>{formatCount(failures)}</dd>
                    </div>
                    {row.error_summary ? (
                      <div className="sm:col-span-2">
                        <dt className="text-muted-foreground">Ошибка цикла</dt>
                        <dd className="mt-1 rounded border border-border/50 bg-muted/20 px-2 py-1">
                          {row.error_summary}
                        </dd>
                      </div>
                    ) : null}
                  </dl>
                </ExpandableTableRow>
              </Fragment>
            );
          })
        )}
      </tbody>
    </DataTableShell>
  );
}
