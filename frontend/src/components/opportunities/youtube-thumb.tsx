"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";
import { youtubeThumbnail } from "@/lib/attention-format";

export function YoutubeThumb({
  videoId,
  title,
  className,
  compact = false,
}: {
  videoId: string;
  title: string;
  className?: string;
  /** Smaller placeholder for list thumbnails (~144×81). */
  compact?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  if (!videoId || failed) {
    return (
      <div
        className={cn(
          "flex flex-col items-center justify-center bg-muted/60 text-muted-foreground",
          compact ? "gap-0.5 text-[10px] leading-tight" : "gap-2 text-xs",
          className,
        )}
        aria-hidden
      >
        <span className={compact ? "text-base" : "text-2xl"}>▶</span>
        {!compact ? <span>Обложка недоступна</span> : null}
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={youtubeThumbnail(videoId)}
      alt={title}
      loading="lazy"
      decoding="async"
      className={cn("object-cover", className)}
      onError={() => setFailed(true)}
    />
  );
}
