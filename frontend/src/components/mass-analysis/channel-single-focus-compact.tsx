"use client";

import Image from "next/image";

import { SaveVideoButton } from "@/components/saved-research/save-video-button";
import { formatViewsAndAgeLine } from "@/lib/manual-search-published-format";
import type { ChannelSingleAnalysisPublication } from "@/lib/types";
import { cn, formatDuration, youtubeThumbnail } from "@/lib/utils";

function displayStatsLine(pub: ChannelSingleAnalysisPublication): string | null {
  const publishedHint = pub.published_text || pub.published_at || undefined;
  return formatViewsAndAgeLine(pub.views_count, publishedHint);
}

function durationLabel(pub: ChannelSingleAnalysisPublication): string | null {
  if (pub.duration_text?.trim()) {
    return pub.duration_text.trim();
  }
  if (pub.duration_seconds != null && pub.duration_seconds > 0) {
    return formatDuration(pub.duration_seconds);
  }
  return null;
}

export function ChannelSingleFocusCompact({
  pub,
  channelTitle,
  viewsRankCaption,
  className,
}: {
  pub: ChannelSingleAnalysisPublication;
  channelTitle: string;
  viewsRankCaption: string | null;
  className?: string;
}) {
  const thumb = pub.thumbnail_url || youtubeThumbnail(pub.video_id);
  const stats = displayStatsLine(pub);
  const duration = durationLabel(pub);

  return (
    <div
      className={cn(
        "flex flex-col gap-4 rounded-lg border border-primary/40 bg-card p-4 sm:flex-row sm:items-start",
        className,
      )}
    >
      <a
        href={pub.url}
        target="_blank"
        rel="noopener noreferrer"
        className="relative mx-auto w-full max-w-[280px] shrink-0 sm:mx-0"
      >
        <div className="relative aspect-video overflow-hidden rounded-md bg-muted">
          <Image
            src={thumb}
            alt=""
            width={280}
            height={158}
            unoptimized
            className="h-full w-full object-cover"
          />
          {duration ? (
            <span className="absolute bottom-2 right-2 rounded bg-black/80 px-1.5 py-0.5 text-xs text-white">
              {duration}
            </span>
          ) : null}
        </div>
      </a>
      <div className="min-w-0 flex-1 space-y-2">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Выбранное видео
        </p>
        <a
          href={pub.url}
          target="_blank"
          rel="noopener noreferrer"
          className="line-clamp-3 text-base font-semibold hover:text-primary"
        >
          {pub.title || pub.video_id}
        </a>
        <p className="text-sm text-muted-foreground">{channelTitle}</p>
        {stats ? <p className="text-sm text-muted-foreground">{stats}</p> : null}
        {viewsRankCaption ? (
          <p className="text-sm text-foreground/90">{viewsRankCaption}</p>
        ) : null}
        <div className="pt-1">
          <SaveVideoButton videoId={pub.video_id} fromManualSearch skipInitialCheck />
        </div>
      </div>
    </div>
  );
}
