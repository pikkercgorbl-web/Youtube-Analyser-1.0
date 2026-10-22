"use client";

import { Badge } from "@/components/ui/badge";
import type { AttentionChannelMomentum, AttentionVideoWinner } from "@/lib/attention-types";
import { pickOpportunityVideoBadges } from "@/lib/opportunity-winner-presentation";
import { cn } from "@/lib/utils";

export function OpportunityVideoSignalBadges({
  video,
  channelMomentum = [],
  className,
}: {
  video: AttentionVideoWinner;
  channelMomentum?: AttentionChannelMomentum[];
  className?: string;
}) {
  const labels = pickOpportunityVideoBadges(video, channelMomentum);
  if (labels.length === 0) {
    return null;
  }
  return (
    <div
      className={cn("flex flex-wrap gap-1.5", className)}
      data-testid="opportunity-video-signal-badges"
    >
      {labels.map((label) => (
        <Badge key={label} variant="outline" className="font-normal text-xs">
          {label}
        </Badge>
      ))}
    </div>
  );
}
