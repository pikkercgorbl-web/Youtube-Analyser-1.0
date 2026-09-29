"use client";

import Link from "next/link";
import { Fragment, useMemo } from "react";

import {
  DataTableHead,
  DataTableRow,
  DataTableShell,
  DataTableTd,
  DataTableTh,
  ExpandableTableRow,
} from "@/components/design-system";
import { LifecycleBadge } from "@/components/design-system/status-badges";
import { formatDateTimeLocal } from "@/lib/monitoring-format";
import {
  ARCHIVED_POOL_HELP,
  POOL_LIFECYCLE_HELP,
  poolLifecycleLabel,
  poolSourceLabel,
  poolStatusReasonLabel,
  SCAN_INTERVAL_TOOLTIP,
} from "@/lib/keyword-pool-copy";
import {
  formatLastScan,
  formatNextScanPresentation,
  formatScanIntervalSeconds,
} from "@/lib/keyword-pool-format";
import type { TargetKeywordItem } from "@/lib/keyword-pool-types";
import { cn } from "@/lib/utils";

export function KeywordPoolTable({
  rows,
  keywordById,
  now,
}: {
  rows: TargetKeywordItem[];
  keywordById: Map<number, string>;
  now: Date;
}) {
  const colSpan = 6;

  const parentLabel = useMemo(() => {
    return (parentId: number | null) => {
      if (parentId == null) {
        return null;
      }
      return keywordById.get(parentId) ?? null;
    };
  }, [keywordById]);

  return (
    <DataTableShell minWidthClassName="min-w-[880px]" className="text-sm" data-testid="keyword-pool-table">
      <DataTableHead>
        <tr>
          <DataTableTh>Keyword</DataTableTh>
          <DataTableTh>Lifecycle</DataTableTh>
          <DataTableTh>Source</DataTableTh>
          <DataTableTh>Следующий скан</DataTableTh>
          <DataTableTh>Расписание</DataTableTh>
          <DataTableTh>Последний скан</DataTableTh>
        </tr>
      </DataTableHead>
      <tbody>
        {rows.map((row) => {
          const nextScan = formatNextScanPresentation(row, now);
          const lastScan = formatLastScan(row.last_checked);
          const parent = parentLabel(row.parent_keyword_id);

          return (
            <Fragment key={row.id}>
              <DataTableRow data-testid={`pool-row-${row.id}`}>
                <DataTableTd emphasis>{row.keyword}</DataTableTd>
                <DataTableTd>
                  <LifecycleBadge
                    status={row.lifecycle_status}
                    label={poolLifecycleLabel(row.lifecycle_status)}
                    title={POOL_LIFECYCLE_HELP}
                  />
                </DataTableTd>
                <DataTableTd>{poolSourceLabel(row.source_type)}</DataTableTd>
                <DataTableTd>
                  <span
                    title={nextScan.title}
                    className={cn(
                      nextScan.text === "Пора сканировать" && "font-medium text-status-warn",
                    )}
                  >
                    {nextScan.text}
                  </span>
                </DataTableTd>
                <DataTableTd>
                  <span title={SCAN_INTERVAL_TOOLTIP}>
                    {row.lifecycle_status === "archived"
                      ? "—"
                      : formatScanIntervalSeconds(row.scan_interval_seconds)}
                  </span>
                </DataTableTd>
                <DataTableTd muted>
                  <span title={lastScan.title}>{lastScan.text}</span>
                </DataTableTd>
              </DataTableRow>
              <ExpandableTableRow colSpan={colSpan} summary="Технические детали">
                <dl className="grid gap-2 text-xs sm:grid-cols-2">
                  <div>
                    <dt className="text-muted-foreground">ID</dt>
                    <dd>{row.id}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Источник (тип)</dt>
                    <dd>{poolSourceLabel(row.source_type)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Создан из</dt>
                    <dd>
                      {parent
                        ? parent
                        : row.parent_keyword_id != null
                          ? "Родительский ключ недоступен"
                          : "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">status_changed_at</dt>
                    <dd>{formatDateTimeLocal(row.status_changed_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">next_scan_at</dt>
                    <dd>{formatDateTimeLocal(row.next_scan_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Интервал (сек)</dt>
                    <dd>{row.scan_interval_seconds ?? "—"}</dd>
                  </div>
                  <div className="sm:col-span-2">
                    <dt className="text-muted-foreground">Причина текущего статуса</dt>
                    <dd>{poolStatusReasonLabel(row.status_reason)}</dd>
                  </div>
                  {row.lifecycle_status === "archived" ? (
                    <div className="sm:col-span-2 text-muted-foreground">{ARCHIVED_POOL_HELP}</div>
                  ) : null}
                </dl>
                <div className="pt-3">
                  <Link
                    href={`/keyword-performance/${row.id}`}
                    className="text-sm text-primary hover:underline"
                    data-testid={`pool-performance-link-${row.id}`}
                  >
                    Производительность
                  </Link>
                </div>
              </ExpandableTableRow>
            </Fragment>
          );
        })}
      </tbody>
    </DataTableShell>
  );
}
