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
        className={cn(
          "flex flex-col gap-2 items-center justify-center bg-muted/60 text-xs text-muted-foreground",
          className,
        )}
        aria-hidden
      >
        <span className="text-2xl">▶</span>
        <span>Обложка недоступна</span>
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
