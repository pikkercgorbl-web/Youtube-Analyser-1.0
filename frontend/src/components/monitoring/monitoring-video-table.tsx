"use client";

import Link from "next/link";
import { Fragment } from "react";

import {
  CapturePoolBadge,
  MonitoringStatusBadge,
  TierBadge,
} from "@/components/monitoring/monitoring-badges";
import {
  DataTableHead,
  DataTableRow,
  DataTableShell,
  DataTableTd,
  DataTableTh,
  ExpandableTableRow,
} from "@/components/design-system";
import { CAPTURE_POOL_HELP } from "@/lib/monitoring-summaries";
import {
  formatAgeHours,
  formatDateTimeLocal,
  formatMonitoringViews,
  formatMonitoringVph,
  formatSnapshotRelative,
} from "@/lib/monitoring-format";
import type { MonitoringVideoListItem } from "@/lib/monitoring-types";
import { textRoles } from "@/lib/design-system/typography";
import { cn } from "@/lib/utils";

function SnapshotFreshness({
  iso,
  referenceMs,
}: {
  iso: string | null | undefined;
  referenceMs: number;
}) {
  const label = formatSnapshotRelative(iso, referenceMs);
  return (
    <span title={formatDateTimeLocal(iso)} className={textRoles.tableCellMuted}>
      {label}
    </span>
  );
}

function VideoTitleCell({ row }: { row: MonitoringVideoListItem }) {
  return (
    <DataTableTd emphasis className="max-w-[240px]">
      <Link
        href={`/monitoring/videos/${row.video_id}`}
        className="line-clamp-2 font-medium text-primary hover:underline"
      >
        {row.title ?? row.video_id}
      </Link>
    </DataTableTd>
  );
}

function TechnicalRowDetails({ row, referenceMs }: { row: MonitoringVideoListItem; referenceMs: number }) {
  return (
    <dl className={cn(textRoles.metadata, "grid gap-2 sm:grid-cols-2")}>
      <div>
        <dt className="text-muted-foreground">video_id</dt>
        <dd className={textRoles.code}>{row.video_id}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">channel_id</dt>
        <dd className={textRoles.code}>{row.channel_id}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">VPH</dt>
        <dd>{formatMonitoringVph(row.current_vph)}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">Просмотры</dt>
        <dd>{formatMonitoringViews(row.current_views)}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">Возраст</dt>
        <dd>{formatAgeHours(row.age_hours)}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">Снимок (точное время)</dt>
        <dd>{formatDateTimeLocal(row.latest_snapshot_at)}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">Свежесть снимка</dt>
        <dd>{formatSnapshotRelative(row.latest_snapshot_at, referenceMs)}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">Пул наблюдения</dt>
        <dd>
          {row.in_active_capture_pool != null ? (
            <CapturePoolBadge inActiveCapturePool={row.in_active_capture_pool} title={CAPTURE_POOL_HELP} />
          ) : (
            "—"
          )}
        </dd>
      </div>
      <div>
        <dt className="text-muted-foreground">monitoring_status</dt>
        <dd className={textRoles.code}>{row.monitoring_status}</dd>
      </div>
      {row.due_checkpoint_hours.length > 0 ? (
        <div>
          <dt className="text-muted-foreground">due checkpoints (h)</dt>
          <dd>{row.due_checkpoint_hours.join(", ")}</dd>
        </div>
      ) : null}
      {row.overdue_checkpoint_hours.length > 0 ? (
        <div>
          <dt className="text-muted-foreground">overdue checkpoints (h)</dt>
          <dd>{row.overdue_checkpoint_hours.join(", ")}</dd>
        </div>
      ) : null}
    </dl>
  );
}

export function PriorityVideosTable({
  videos,
  referenceMs,
}: {
  videos: MonitoringVideoListItem[];
  referenceMs: number;
}) {
  const colSpan = 5;

  return (
    <DataTableShell minWidthClassName="min-w-[720px]" className="text-sm">
      <DataTableHead>
        <tr>
          <DataTableTh>Видео</DataTableTh>
          <DataTableTh>Канал</DataTableTh>
          <DataTableTh>Состояние</DataTableTh>
          <DataTableTh>След. контрольная точка</DataTableTh>
          <DataTableTh>Tier</DataTableTh>
        </tr>
      </DataTableHead>
      <tbody>
        {videos.map((row) => (
          <Fragment key={row.video_id}>
            <DataTableRow>
              <VideoTitleCell row={row} />
              <DataTableTd muted>{row.channel_title ?? row.channel_id}</DataTableTd>
              <DataTableTd>
                <MonitoringStatusBadge item={row} />
              </DataTableTd>
              <DataTableTd align="right" muted>
                {row.next_checkpoint_hours != null ? `${row.next_checkpoint_hours} ч` : "—"}
              </DataTableTd>
              <DataTableTd>
                <TierBadge tier={row.tier} />
              </DataTableTd>
            </DataTableRow>
            <ExpandableTableRow colSpan={colSpan} summary="Технические детали">
              <TechnicalRowDetails row={row} referenceMs={referenceMs} />
            </ExpandableTableRow>
          </Fragment>
        ))}
      </tbody>
    </DataTableShell>
  );
}

export function BreakoutVideosTable({
  videos,
  referenceMs,
}: {
  videos: MonitoringVideoListItem[];
  referenceMs: number;
}) {
  const colSpan = 7;

  return (
    <DataTableShell minWidthClassName="min-w-[800px]" className="text-sm">
      <DataTableHead>
        <tr>
          <DataTableTh align="right">Место</DataTableTh>
          <DataTableTh>Видео</DataTableTh>
          <DataTableTh>Канал</DataTableTh>
          <DataTableTh align="right">VPH</DataTableTh>
          <DataTableTh align="right">Просмотры</DataTableTh>
          <DataTableTh align="right">Возраст</DataTableTh>
          <DataTableTh>Свежесть снимка</DataTableTh>
        </tr>
      </DataTableHead>
      <tbody>
        {videos.map((row) => (
          <Fragment key={row.video_id}>
            <DataTableRow>
              <DataTableTd align="right" muted>
                {row.breakout_rank != null ? `#${row.breakout_rank}` : "—"}
              </DataTableTd>
              <VideoTitleCell row={row} />
              <DataTableTd muted>{row.channel_title ?? row.channel_id}</DataTableTd>
              <DataTableTd align="right" emphasis>
                {formatMonitoringVph(row.current_vph ?? row.breakout_ranking_value)}
              </DataTableTd>
              <DataTableTd align="right">{formatMonitoringViews(row.current_views)}</DataTableTd>
              <DataTableTd align="right" muted>
                {formatAgeHours(row.age_hours)}
              </DataTableTd>
              <DataTableTd>
                <SnapshotFreshness iso={row.latest_snapshot_at} referenceMs={referenceMs} />
              </DataTableTd>
            </DataTableRow>
            <ExpandableTableRow colSpan={colSpan} summary="Контекст мониторинга">
              <dl className={cn(textRoles.metadata, "grid gap-2 sm:grid-cols-2")}>
                <div>
                  <dt className="text-muted-foreground">Tier</dt>
                  <dd>
                    <TierBadge tier={row.tier} />
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Пул наблюдения</dt>
                  <dd>
                    {row.in_active_capture_pool != null ? (
                      <CapturePoolBadge
                        inActiveCapturePool={row.in_active_capture_pool}
                        title={CAPTURE_POOL_HELP}
                      />
                    ) : (
                      "—"
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Снимок</dt>
                  <dd>{formatDateTimeLocal(row.latest_snapshot_at)}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Состояние мониторинга</dt>
                  <dd>
                    <MonitoringStatusBadge item={row} />
                  </dd>
                </div>
              </dl>
            </ExpandableTableRow>
          </Fragment>
        ))}
      </tbody>
    </DataTableShell>
  );
}
