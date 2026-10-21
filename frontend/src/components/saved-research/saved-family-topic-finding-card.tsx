"use client";

import Link from "next/link";
import { ExternalLink } from "lucide-react";

import { YoutubeThumb } from "@/components/opportunities/youtube-thumb";
import { Button } from "@/components/ui/button";
import { formatOptionalViews } from "@/lib/attention-format";
import type { SavedFamilyTopicFinding } from "@/lib/saved-research-types";

type Props = {
  row: SavedFamilyTopicFinding;
  onSave: (id: number) => void;
};

export function SavedFamilyTopicFindingCard({ row, onSave }: Props) {
  const views = formatOptionalViews(row.views_count ?? null);
  return (
    <li className="flex gap-3 rounded-lg border border-border p-3">
      <YoutubeThumb
        videoId={row.video_id}
        title={row.title}
        className="h-16 w-28 shrink-0 rounded object-cover"
      />
      <div className="min-w-0 flex-1 space-y-1 text-sm">
        <p className="font-medium leading-snug">{row.title}</p>
        <p className="text-muted-foreground">{row.channel_title || "—"}</p>
        <p className="text-xs text-muted-foreground">
          Просмотры на YouTube: {views ?? "нет данных"} — это не оценка перспективности темы.
        </p>
        <p className="text-xs font-medium text-primary/90">
          Совпадение в выдаче по утверждённому запросу: «{row.matched_query}»
        </p>
        <p className="text-xs text-muted-foreground">
          Время находки: {new Date(row.last_found_at).toLocaleString()}
        </p>
        <p className="text-xs text-muted-foreground">
          Попадание в выдачу не означает принадлежность к сохранённой PatternFamily.
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={row.saved_to_research}
            onClick={() => onSave(row.id)}
          >
            {row.saved_to_research ? "Уже в сохранённых" : "Сохранить в исследования"}
          </Button>
          <Button type="button" size="sm" variant="ghost" asChild>
            <Link href={row.youtube_url} target="_blank" rel="noopener noreferrer">
              YouTube
              <ExternalLink className="ml-1 h-3 w-3" />
            </Link>
          </Button>
        </div>
      </div>
    </li>
  );
}
