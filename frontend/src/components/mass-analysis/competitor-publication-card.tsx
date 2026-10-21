"use client";

import Image from "next/image";
import Link from "next/link";

import { SaveVideoButton } from "@/components/saved-research/save-video-button";
import { Card, CardContent } from "@/components/ui/card";
import { buildChannelSingleAnalysisUrl } from "@/lib/channel-single-analysis-url";
import { formatViewsAndAgeLine } from "@/lib/manual-search-published-format";
import type { ChannelSingleAnalysisPublication } from "@/lib/types";
import { formatDuration, youtubeThumbnail } from "@/lib/utils";

function durationLabel(pub: ChannelSingleAnalysisPublication): string | null {
  if (pub.duration_text?.trim()) {
    return pub.duration_text.trim();
  }
  if (pub.duration_seconds != null && pub.duration_seconds > 0) {
    return formatDuration(pub.duration_seconds);
  }
  return null;
}

export function CompetitorPublicationCard({
  pub,
  channelTitle,
}: {
  pub: ChannelSingleAnalysisPublication;
  channelTitle: string;
}) {
  const thumb = pub.thumbnail_url || youtubeThumbnail(pub.video_id);
  const stats = formatViewsAndAgeLine(
    pub.views_count > 0 ? pub.views_count : undefined,
    pub.published_text || pub.published_at || undefined,
  );
  const duration = durationLabel(pub);

  return (
    <Card className="overflow-hidden border-border/60">
      <a href={pub.url} target="_blank" rel="noopener noreferrer" className="block">
        <div className="relative aspect-video bg-muted">
          <Image src={thumb} alt="" fill unoptimized className="object-cover" sizes="33vw" />
          {duration ? (
            <span className="absolute bottom-2 right-2 rounded bg-black/80 px-1.5 py-0.5 text-xs text-white">
              {duration}
            </span>
          ) : null}
        </div>
      </a>
      <CardContent className="space-y-2 p-3">
        <a
          href={pub.url}
          target="_blank"
          rel="noopener noreferrer"
          className="line-clamp-2 text-sm font-medium hover:text-primary"
        >
          {pub.title || pub.video_id}
        </a>
        <p className="text-xs text-muted-foreground">{channelTitle}</p>
        {stats ? <p className="text-xs text-muted-foreground">{stats}</p> : null}
        <div className="flex flex-col gap-2 pt-1 sm:flex-row">
          <Link
            href={buildChannelSingleAnalysisUrl({
              channelId: pub.channel_id || "",
              focusVideoId: pub.video_id,
            })}
            className="inline-flex h-9 flex-1 items-center justify-center rounded-md border border-input bg-background px-3 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
          >
            Анализ канала
          </Link>
          <SaveVideoButton videoId={pub.video_id} fromManualSearch skipInitialCheck />
        </div>
      </CardContent>
    </Card>
  );
}
