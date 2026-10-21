"use client";

import Link from "next/link";

import { SaveVideoButton } from "@/components/saved-research/save-video-button";
import { buttonVariants } from "@/components/ui/button";
import {
  canonicalYoutubeUrl,
  formatOptionalAge,
  formatOptionalViews,
  formatOptionalVph,
} from "@/lib/attention-format";
import type { AttentionChannelMomentum, AttentionVideoWinner } from "@/lib/attention-types";
import { OpportunityVideoSignalBadges } from "@/components/opportunities/opportunity-video-signal-badges";
import { surfaces } from "@/lib/design-system/layout";
import { stashWinnerForDetail } from "@/lib/opportunity-winner-cache";
import { opportunityWinnerDetailHref } from "@/lib/opportunity-winner-routes";
import { cn } from "@/lib/utils";

import { YoutubeThumb } from "./youtube-thumb";

export function WinnerCard({
  video,
  channelMomentum = [],
}: {
  video: AttentionVideoWinner;
  channelMomentum?: AttentionChannelMomentum[];
}) {
  const href = canonicalYoutubeUrl(video.video_id, video.youtube_url);
  const displayTitle = video.title || "Видео без названия";
  const views = formatOptionalViews(video.views);
  const vph = formatOptionalVph(video.vph);
  const age = formatOptionalAge(video.age_hours);

  return (
    <article className={cn(surfaces.sectionMuted, "overflow-hidden rounded-2xl")} data-testid="winner-card">
      <a href={href} target="_blank" rel="noopener noreferrer" className="relative block">
        <YoutubeThumb videoId={video.video_id} title={displayTitle} className="aspect-video w-full" />
        {age ? (
          <span className="absolute bottom-2 right-2 rounded-md bg-black/80 px-2 py-0.5 text-xs text-white">
            {age}
          </span>
        ) : null}
      </a>
      <div className="space-y-3 p-3 sm:p-4">
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="line-clamp-2 text-sm font-semibold leading-snug hover:text-primary sm:text-base"
          title={video.title}
        >
          {displayTitle}
        </a>
        <p className="text-xs text-muted-foreground sm:text-sm">{video.channel_title || "Канал неизвестен"}</p>
        <dl className="grid grid-cols-2 gap-3 border-y border-border/60 py-3">
          <div>
            <dt className="text-xs text-muted-foreground">Просмотры</dt>
            <dd className="mt-0.5 text-lg font-semibold tabular-nums">{views ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">В среднем за час</dt>
            <dd className="mt-0.5 text-lg font-semibold tabular-nums text-primary">{vph ?? "—"}</dd>
          </div>
        </dl>
        <OpportunityVideoSignalBadges video={video} channelMomentum={channelMomentum} />
        <div className="flex flex-wrap gap-2">
          <Link
            href={opportunityWinnerDetailHref(video.video_id)}
            className={cn(buttonVariants({ variant: "default", size: "sm" }))}
            onClick={() => stashWinnerForDetail(video)}
          >
            Детали видео
          </Link>
          <Link
            href={`/monitoring/videos/${encodeURIComponent(video.video_id)}`}
            className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
          >
            Динамика видео
          </Link>
          <SaveVideoButton videoId={video.video_id} />
        </div>
      </div>
    </article>
  );
}
