"use client";

import Link from "next/link";

import { YoutubeThumb } from "@/components/opportunities/youtube-thumb";
import { formatOptionalViews, formatOptionalVph } from "@/lib/attention-format";
import { ANALYST_VERDICT_LABELS, SAVED_RESEARCH_STATUS_LABELS } from "@/lib/saved-research-labels";
import { formatMeasurementSource } from "@/lib/saved-research-list-format";
import type { SavedVideoListItem } from "@/lib/saved-research-types";

function viewGrowthLine(row: SavedVideoListItem): string | null {
  if (row.frozen_views == null || row.current_views == null) return null;
  const delta = row.current_views - row.frozen_views;
  if (delta === 0) return "просмотры без изменений";
  return `${delta > 0 ? "+" : ""}${delta.toLocaleString("ru-RU")} просмотров`;
}

export function SavedVideoListItem({ row }: { row: SavedVideoListItem }) {
  const title = row.title?.trim() || "Видео без названия";

  return (
    <li
      className="rounded-xl border border-border p-3"
      data-testid="saved-video-list-item"
    >
      <div className="flex min-w-0 gap-3">
        <div
          className="h-[81px] w-36 shrink-0 overflow-hidden rounded-lg bg-muted"
          data-testid="saved-video-thumb"
        >
          <YoutubeThumb
            videoId={row.video_id}
            title={title}
            compact
            className="h-full w-full object-cover"
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <Link
              href={`/saved/videos/${row.id}`}
              className="font-semibold hover:text-primary break-words"
            >
              {title}
            </Link>
            <span className="shrink-0 text-xs text-muted-foreground">
              {SAVED_RESEARCH_STATUS_LABELS[row.status]}
            </span>
          </div>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">{row.channel_title}</p>
          <p className="mt-2 text-sm tabular-nums">
            {formatOptionalViews(row.frozen_views) ?? "—"} →{" "}
            {formatOptionalViews(row.current_views) ?? "—"}
            {viewGrowthLine(row) ? ` (${viewGrowthLine(row)})` : ""}
            {" · "}
            VPH {formatOptionalVph(row.frozen_vph) ?? "—"} →{" "}
            {formatOptionalVph(row.current_vph) ?? "—"}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Измерение: {formatMeasurementSource(row.latest_measurement_source)}
            {row.latest_observed_at
              ? ` · ${new Date(row.latest_observed_at).toLocaleString()}`
              : ""}
          </p>
          {row.latest_analyst_verdict ? (
            <p className="mt-1 text-xs">
              Оценка: {ANALYST_VERDICT_LABELS[row.latest_analyst_verdict]}
            </p>
          ) : null}
          {row.in_current_attention === false ? (
            <p className="mt-1 text-xs text-muted-foreground">Вне текущей выборки Attention.</p>
          ) : null}
        </div>
      </div>
    </li>
  );
}
