"use client";

import Link from "next/link";
import { Fragment } from "react";

import {
  DataTableHead,
  DataTableRow,
  DataTableShell,
  DataTableTd,
  DataTableTh,
  ExpandableTableRow,
  InfoTooltip,
} from "@/components/design-system";
import { formatRelativeFromReference } from "@/components/design-system/freshness";
import { EvidenceBadge, LifecycleBadge } from "@/components/design-system/status-badges";
import {
  CROSS_KEYWORD_DUP_HELP,
  keywordEvidenceStatusLabel,
  LIFECYCLE_NOT_QUALITY,
  NEW_TO_CORPUS_HELP,
  sourceTypeLabel,
  VPH_AT_DISCOVERY_TOOLTIP,
} from "@/lib/keyword-performance-copy";
import {
  formatOptionalNumber,
  formatRateFraction,
  formatTopDecileBreakoutRate,
  formatVph,
} from "@/lib/keyword-performance-format";
import type { KeywordPerformanceMetrics } from "@/lib/keyword-performance-types";
import { formatDateTimeLocal } from "@/lib/monitoring-format";
import { textRoles } from "@/lib/design-system/typography";
import { cn } from "@/lib/utils";

function KeywordLink({ row }: { row: KeywordPerformanceMetrics }) {
  return (
    <Link
      href={`/keyword-performance/${row.keyword_id}`}
      className="font-medium text-primary hover:underline"
    >
      {row.keyword}
    </Link>
  );
}

function DiscoveryExpansion({ row }: { row: KeywordPerformanceMetrics }) {
  return (
    <dl className={cn(textRoles.metadata, "grid gap-2 sm:grid-cols-2")}>
      <div>
        <dt className="text-muted-foreground">Атрибутировано видео</dt>
        <dd>{formatOptionalNumber(row.attributed_video_count)}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">Пересечения с другими ключами</dt>
        <dd title={CROSS_KEYWORD_DUP_HELP}>
          {formatOptionalNumber(row.cross_keyword_duplicate_count)}
          {row.duplicate_rate != null ? ` (${formatRateFraction(row.duplicate_rate)})` : null}
        </dd>
      </div>
      <div>
        <dt className="text-muted-foreground">VPH p90 при находке</dt>
        <dd>{formatVph(row.p90_vph_at_discovery)}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">Сканов</dt>
        <dd>{row.scan_count}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">Источник</dt>
        <dd>{sourceTypeLabel(row.source_type)}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">keyword_id</dt>
        <dd className={textRoles.code}>{row.keyword_id}</dd>
      </div>
      {row.evidence_detail ? (
        <>
          <div>
            <dt className="text-muted-foreground">Breakout-eligible (детали)</dt>
            <dd>{row.evidence_detail.breakout_eligible_video_count}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">72h obs (детали)</dt>
            <dd>{row.evidence_detail.observed_72h_video_count}</dd>
          </div>
        </>
      ) : null}
    </dl>
  );
}

export function DiscoveryPerformanceTable({
  items,
  referenceIso,
}: {
  items: KeywordPerformanceMetrics[];
  referenceIso: string | null;
}) {
  const colSpan = 7;

  return (
    <DataTableShell minWidthClassName="min-w-[880px]" className="text-sm">
      <DataTableHead>
        <tr>
          <DataTableTh>Ключ</DataTableTh>
          <DataTableTh>Lifecycle</DataTableTh>
          <DataTableTh align="right">Найдено видео</DataTableTh>
          <DataTableTh align="right">
            <span className="inline-flex items-center gap-1">
              Новых для базы
              <InfoTooltip content={NEW_TO_CORPUS_HELP} label="Пояснение: новые для базы" />
            </span>
          </DataTableTh>
          <DataTableTh align="right">
            <span className="inline-flex items-center gap-1">
              VPH при находке
              <InfoTooltip content={VPH_AT_DISCOVERY_TOOLTIP} label="Пояснение VPH" />
            </span>
          </DataTableTh>
          <DataTableTh>Последний скан</DataTableTh>
          <DataTableTh>Достаточность данных</DataTableTh>
        </tr>
      </DataTableHead>
      <tbody>
        {items.map((row) => {
          const lastScan = formatRelativeFromReference(row.last_scan_at, referenceIso);
          return (
            <Fragment key={row.keyword_id}>
              <DataTableRow>
                <DataTableTd emphasis>
                  <KeywordLink row={row} />
                </DataTableTd>
                <DataTableTd>
                  <LifecycleBadge status={row.lifecycle_status} title={LIFECYCLE_NOT_QUALITY} />
                </DataTableTd>
                <DataTableTd align="right">{formatOptionalNumber(row.unique_video_count)}</DataTableTd>
                <DataTableTd align="right" emphasis>
                  {formatOptionalNumber(row.new_to_corpus_video_count)}
                </DataTableTd>
                <DataTableTd align="right">{formatVph(row.median_vph_at_discovery)}</DataTableTd>
                <DataTableTd muted>
                  <span title={formatDateTimeLocal(row.last_scan_at)}>
                    {row.last_scan_at ? lastScan.relative : "сканов не было"}
                  </span>
                </DataTableTd>
                <DataTableTd>
                  <EvidenceBadge
                    status={row.evidence_status}
                    label={keywordEvidenceStatusLabel(row.evidence_status)}
                  />
                </DataTableTd>
              </DataTableRow>
              <ExpandableTableRow colSpan={colSpan} summary="Аналитические детали">
                <DiscoveryExpansion row={row} />
              </ExpandableTableRow>
            </Fragment>
          );
        })}
      </tbody>
    </DataTableShell>
  );
}

export function BreakoutPerformanceTable({
  items,
  globalEligible,
}: {
  items: KeywordPerformanceMetrics[];
  globalEligible: number | null | undefined;
}) {
  const colSpan = 6;

  return (
    <DataTableShell minWidthClassName="min-w-[820px]" className="text-sm">
      <DataTableHead>
        <tr>
          <DataTableTh>Ключ</DataTableTh>
          <DataTableTh align="right">Подходят для breakout</DataTableTh>
          <DataTableTh align="right">В top-decile</DataTableTh>
          <DataTableTh align="right">Доля top-decile</DataTableTh>
          <DataTableTh align="right">VPH при находке</DataTableTh>
          <DataTableTh>Достаточность данных</DataTableTh>
        </tr>
      </DataTableHead>
      <tbody>
        {items.map((row) => (
          <Fragment key={row.keyword_id}>
            <DataTableRow>
              <DataTableTd emphasis>
                <KeywordLink row={row} />
              </DataTableTd>
              <DataTableTd align="right">
                {formatOptionalNumber(row.breakout_eligible_video_count)}
              </DataTableTd>
              <DataTableTd align="right">
                {formatOptionalNumber(row.top_decile_breakout_count ?? row.confirmed_breakout_count)}
              </DataTableTd>
              <DataTableTd align="right">
                <span data-testid={`breakout-rate-${row.keyword_id}`}>
                  {formatTopDecileBreakoutRate(row.top_decile_breakout_rate, globalEligible)}
                </span>
              </DataTableTd>
              <DataTableTd align="right">{formatVph(row.median_vph_at_discovery)}</DataTableTd>
              <DataTableTd>
                <EvidenceBadge
                  status={row.evidence_status}
                  label={keywordEvidenceStatusLabel(row.evidence_status)}
                />
              </DataTableTd>
            </DataTableRow>
            <ExpandableTableRow colSpan={colSpan} summary="Дополнительно">
              <dl className={cn(textRoles.metadata, "grid gap-2 sm:grid-cols-2")}>
                <div>
                  <dt className="text-muted-foreground">Median VPH сейчас</dt>
                  <dd>{formatVph(row.median_current_vph)}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Найдено видео</dt>
                  <dd>{formatOptionalNumber(row.unique_video_count)}</dd>
                </div>
              </dl>
            </ExpandableTableRow>
          </Fragment>
        ))}
      </tbody>
    </DataTableShell>
  );
}

function Observed72hCell({ row }: { row: KeywordPerformanceMetrics }) {
  const n = row.observed_72h_video_count ?? 0;
  if (n === 0) {
    return (
      <span className="text-muted-foreground" data-testid={`observed-72h-${row.keyword_id}`}>
        Исходов пока нет
      </span>
    );
  }
  return (
    <span data-testid={`observed-72h-${row.keyword_id}`} className="tabular-nums">
      {formatOptionalNumber(n)}
    </span>
  );
}

export function OutcomesPerformanceTable({ items }: { items: KeywordPerformanceMetrics[] }) {
  const colSpan = 5;

  return (
    <DataTableShell minWidthClassName="min-w-[720px]" className="text-sm">
      <DataTableHead>
        <tr>
          <DataTableTh>Ключ</DataTableTh>
          <DataTableTh>Валидные исходы 72 ч</DataTableTh>
          <DataTableTh>Без подходящего снимка</DataTableTh>
          <DataTableTh align="right">Медиана роста просмотров 72 ч</DataTableTh>
          <DataTableTh>Достаточность данных</DataTableTh>
        </tr>
      </DataTableHead>
      <tbody>
        {items.map((row) => (
          <Fragment key={row.keyword_id}>
            <DataTableRow>
              <DataTableTd emphasis>
                <KeywordLink row={row} />
              </DataTableTd>
              <DataTableTd>
                <Observed72hCell row={row} />
              </DataTableTd>
              <DataTableTd muted className="text-muted-foreground">
                {formatOptionalNumber(row.missing_72h_video_count)}
              </DataTableTd>
              <DataTableTd align="right">
                {(row.observed_72h_video_count ?? 0) === 0
                  ? "—"
                  : formatOptionalNumber(row.median_absolute_view_growth_72h)}
              </DataTableTd>
              <DataTableTd>
                <EvidenceBadge
                  status={row.evidence_status}
                  label={keywordEvidenceStatusLabel(row.evidence_status)}
                />
              </DataTableTd>
            </DataTableRow>
            <ExpandableTableRow colSpan={colSpan} summary="Детали evidence">
              <DiscoveryExpansion row={row} />
            </ExpandableTableRow>
          </Fragment>
        ))}
      </tbody>
    </DataTableShell>
  );
}
