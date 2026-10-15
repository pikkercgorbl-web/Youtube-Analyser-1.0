"use client";

import Link from "next/link";

import { SaveVideoButton } from "@/components/saved-research/save-video-button";
import { buttonVariants } from "@/components/ui/button";
import { canonicalYoutubeUrl } from "@/lib/attention-format";
import type { AttentionPatternMemberVideo } from "@/lib/attention-types";
import {
  memberDisplayMetrics,
  memberMetricCaption,
} from "@/lib/family-member-metrics";
import { opportunityWinnerDetailHref } from "@/lib/opportunity-winner-routes";
import { surfaces } from "@/lib/design-system/layout";
import { cn } from "@/lib/utils";

import { YoutubeThumb } from "./youtube-thumb";

export function FamilyMemberCard({
  video,
  snapshotComputedAt,
  highlightFeedWinner = false,
}: {
  video: AttentionPatternMemberVideo;
  snapshotComputedAt: string | null;
  highlightFeedWinner?: boolean;
}) {
  const youtubeHref = canonicalYoutubeUrl(video.video_id, video.youtube_url);
  const title = video.title?.trim() || "Видео без названия";
  const metrics = memberDisplayMetrics(video);
  const caption = memberMetricCaption(video, snapshotComputedAt);
  const inWinners = video.in_winner_snapshot;

  return (
    <article
      className={cn(
        surfaces.section,
        "flex flex-col overflow-hidden rounded-xl",
        (highlightFeedWinner || inWinners) &&
          "border-amber-400/40 ring-1 ring-amber-400/20",
      )}
      data-testid="family-member-card"
      data-feed-winner={highlightFeedWinner ? "true" : undefined}
      data-in-winner-snapshot={inWinners ? "true" : undefined}
    >
      <a
        href={youtubeHref}
        target="_blank"
        rel="noopener noreferrer"
        className="relative block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-inset"
        aria-label={`Открыть «${title}» на YouTube`}
      >
        <YoutubeThumb
          videoId={video.video_id}
          title={title}
          className="aspect-video w-full bg-muted"
        />
      </a>
      <div className="flex flex-1 flex-col gap-2 p-3">
        <div className="flex flex-wrap items-start gap-2">
          <h3 className="min-w-0 flex-1 text-sm font-semibold leading-snug">
            <a
              href={youtubeHref}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              title={title}
            >
              {title}
            </a>
          </h3>
          {inWinners ? (
            <span
              className="shrink-0 rounded-md bg-amber-400/15 px-2 py-0.5 text-xs font-semibold text-amber-100"
              data-testid="family-member-winner-badge"
            >
              {video.breakout_rank != null
                ? `Winner · Radar #${video.breakout_rank}`
                : "Winner · этот run"}
            </span>
          ) : (
            <span className="shrink-0 rounded-md border border-border/60 px-2 py-0.5 text-xs text-muted-foreground">
              Участник запроса
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground">{video.channel_title || "Канал неизвестен"}</p>
        <dl className="grid grid-cols-2 gap-2 text-xs">
          <div>
            <dt className="text-muted-foreground">Просмотры</dt>
            <dd className="font-semibold tabular-nums">{metrics.views}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">VPH</dt>
            <dd className="font-semibold tabular-nums text-primary">{metrics.vph}</dd>
          </div>
        </dl>
        <p
          className="text-[11px] leading-snug text-muted-foreground"
          data-testid="member-measurement-status"
        >
          {caption}
          {metrics.age !== "Нет измерения" ? ` · возраст ${metrics.age}` : null}
        </p>
        <div className="mt-auto flex flex-wrap gap-2 pt-1">
          {inWinners ? (
            <Link
              href={opportunityWinnerDetailHref(video.video_id)}
              className={cn(buttonVariants({ variant: "default", size: "sm" }))}
            >
              Детали видео
            </Link>
          ) : null}
          <SaveVideoButton videoId={video.video_id} />
        </div>
      </div>
    </article>
  );
}
