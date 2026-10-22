"use client";

import {
  canonicalYoutubeUrl,
  formatOptionalAge,
  formatOptionalViews,
  formatOptionalVph,
} from "@/lib/attention-format";
import type { AttentionPatternMemberVideo } from "@/lib/attention-types";
import {
  formatViewsWithMeasurementStatus,
  viewsMeasurementLabel,
} from "@/lib/views-measurement-status";
import { surfaces } from "@/lib/design-system/layout";
import { cn } from "@/lib/utils";

import { AttentionSignalBadges, HumanReasonsList } from "./signal-badges";
import { WinnerFeedLink } from "./winner-feed-link";
import { YoutubeThumb } from "./youtube-thumb";

export function PatternMemberRow({
  video,
  highlightFeedWinner = false,
}: {
  video: AttentionPatternMemberVideo;
  highlightFeedWinner?: boolean;
}) {
  const href = canonicalYoutubeUrl(video.video_id, video.youtube_url);
  const status = video.views_measurement_status ?? "missing_snapshot";
  const viewsText = formatViewsWithMeasurementStatus(
    formatOptionalViews(video.views),
    status,
  );

  return (
    <article
      className={cn(
        surfaces.sectionMuted,
        "flex gap-3 p-3",
        highlightFeedWinner && "border-amber-400/35 ring-1 ring-amber-400/25",
      )}
      data-testid="pattern-member"
      data-feed-winner={highlightFeedWinner ? "true" : undefined}
    >
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="shrink-0"
        aria-label={`Открыть «${video.title}» на YouTube`}
      >
        <YoutubeThumb
          videoId={video.video_id}
          title={video.title}
          className="h-20 w-36 rounded"
        />
      </a>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-start gap-2">
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium hover:text-primary"
          >
            {video.title}
          </a>
          {highlightFeedWinner ? (
            <WinnerFeedLink
              videoId={video.video_id}
              className="rounded-md bg-amber-400/15 px-2 py-0.5 text-xs font-semibold text-amber-100"
            >
              Winner в подборке
            </WinnerFeedLink>
          ) : null}
        </div>
        <p className="text-xs text-muted-foreground">{video.channel_title}</p>
        <p
          className="mt-1 text-xs text-muted-foreground"
          data-testid="member-measurement-status"
        >
          {viewsMeasurementLabel(status)}
          {formatOptionalVph(video.vph) ? ` · ${formatOptionalVph(video.vph)}` : ""}
          {formatOptionalAge(video.age_hours) ? ` · ${formatOptionalAge(video.age_hours)}` : ""}
        </p>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs tabular-nums">
          <span>Просмотры: {viewsText}</span>
          {video.in_winner_snapshot && !highlightFeedWinner ? (
            <span>в сегодняшнем топе Winners</span>
          ) : null}
        </div>
        <AttentionSignalBadges
          treatAsWinner={video.in_winner_snapshot}
          inWinnerSnapshot={video.in_winner_snapshot}
          reasonCodes={video.reason_codes}
          accelerationState={video.acceleration_state}
          delayedOutcomeState={video.delayed_outcome_state}
        />
        <HumanReasonsList reasons={video.human_reasons} />
      </div>
    </article>
  );
}
