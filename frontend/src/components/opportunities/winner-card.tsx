"use client";

import {
  canonicalYoutubeUrl,
  formatOptionalAge,
  formatOptionalSubscribers,
  formatOptionalViews,
  formatOptionalVph,
} from "@/lib/attention-format";
import type { AttentionVideoWinner } from "@/lib/attention-types";
import { surfaces } from "@/lib/design-system/layout";
import { cn } from "@/lib/utils";

import { HumanReasonsList, AttentionSignalBadges } from "./signal-badges";
import { YoutubeThumb } from "./youtube-thumb";

export function WinnerCard({ video }: { video: AttentionVideoWinner }) {
  const href = canonicalYoutubeUrl(video.video_id, video.youtube_url);
  const views = formatOptionalViews(video.views);
  const vph = formatOptionalVph(video.vph);
  const age = formatOptionalAge(video.age_hours);
  const subs = formatOptionalSubscribers(video.subscribers);
  return (
    <article className={cn(surfaces.sectionMuted, "overflow-hidden")} data-testid="winner-card">
      <a href={href} target="_blank" rel="noopener noreferrer" className="block">
        <YoutubeThumb videoId={video.video_id} title={video.title} className="aspect-video w-full" />
      </a>
      <div className="space-y-2 p-3">
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="line-clamp-2 text-sm font-medium leading-snug hover:text-primary"
        >
          {video.title}
        </a>
        <p className="text-xs text-muted-foreground">{video.channel_title}</p>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
          {vph ? <span className="font-semibold text-amber-200">{vph}</span> : null}
          {views ? <span>{views} views</span> : null}
          {age ? <span>{age}</span> : null}
          {video.breakout_rank != null ? <span>Breakout #{video.breakout_rank}</span> : null}
          {subs ? <span>{subs} подп.</span> : null}
        </div>
        <AttentionSignalBadges
          treatAsWinner
          reasonCodes={video.reason_codes}
          accelerationState={video.acceleration_state}
          delayedOutcomeState={video.delayed_outcome_state}
          channelRelativeStatus={video.channel_relative_signal?.status}
        />
        <HumanReasonsList reasons={video.human_reasons} />
      </div>
    </article>
  );
}
