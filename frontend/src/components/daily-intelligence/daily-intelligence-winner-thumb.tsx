"use client";

import { useState } from "react";

import { dailyIntelligenceThumbnailUrl } from "@/lib/daily-intelligence-youtube";
import { cn } from "@/lib/utils";

export function DailyIntelligenceWinnerThumb({
  videoId,
  title,
  href,
  className,
}: {
  videoId: string;
  title: string;
  href: string;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  const src = dailyIntelligenceThumbnailUrl(videoId);
  const showFallback = !src || failed;

  const thumb = showFallback ? (
    <div
      className={cn(
        "flex aspect-video w-[120px] shrink-0 flex-col items-center justify-center rounded-md bg-muted/60 text-[10px] leading-tight text-muted-foreground",
        className,
      )}
      aria-hidden
    >
      <span className="text-lg">▶</span>
      <span>Нет превью</span>
    </div>
  ) : (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt=""
      loading="lazy"
      decoding="async"
      width={120}
      height={68}
      className={cn(
        "aspect-video h-[68px] w-[120px] shrink-0 rounded-md object-cover bg-muted",
        className,
      )}
      onError={() => setFailed(true)}
    />
  );

  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="shrink-0 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      aria-label={title ? `Открыть на YouTube: ${title}` : "Открыть на YouTube"}
    >
      {thumb}
    </a>
  );
}
