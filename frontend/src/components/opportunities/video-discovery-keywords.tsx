"use client";

import type { AttentionRelatedKeyword } from "@/lib/attention-types";

export function VideoDiscoveryKeywords({
  videoId,
  keywords,
  className,
}: {
  videoId: string;
  keywords: AttentionRelatedKeyword[];
  className?: string;
}) {
  if (keywords.length === 0) {
    return (
      <p className={className} data-testid="video-discovery-keywords-empty">
        Запросы обнаружения для этого видео в снимке не сохранены.
      </p>
    );
  }
  return (
    <div className={className} data-testid="video-discovery-keywords">
      <p className="text-sm font-medium text-foreground">
        Запросы, по которым нашли это видео
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        Видео <span className="font-mono">{videoId}</span> · запрос — источник
        поиска Radar, не тема ролика и не доказательство сходства с другими
        участниками подборки.
      </p>
      <ul className="mt-2 flex flex-wrap gap-2">
        {keywords.map((row) => (
          <li
            key={row.keyword_id}
            className="rounded-full border border-border/60 px-3 py-1 text-sm"
          >
            {row.keyword}
          </li>
        ))}
      </ul>
    </div>
  );
}
