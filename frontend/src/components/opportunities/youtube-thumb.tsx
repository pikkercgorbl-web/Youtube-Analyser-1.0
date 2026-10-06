"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";
import { youtubeThumbnail } from "@/lib/attention-format";

export function YoutubeThumb({
  videoId,
  title,
  className,
}: {
  videoId: string;
  title: string;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  if (!videoId || failed) {
    return (
      <div
        className={cn("flex items-center justify-center bg-muted/60 text-[10px] text-muted-foreground", className)}
        aria-hidden
      >
        ▶
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={youtubeThumbnail(videoId)}
      alt={title}
      className={cn("object-cover", className)}
      onError={() => setFailed(true)}
    />
  );
}
