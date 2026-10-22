"use client";

import Link from "next/link";
import { ExternalLink } from "lucide-react";

import { YoutubeThumb } from "@/components/opportunities/youtube-thumb";
import { Button } from "@/components/ui/button";
import { formatOptionalViews } from "@/lib/attention-format";
import type { SavedVideoSimilarFinding } from "@/lib/saved-research-types";

type Props = {
  row: SavedVideoSimilarFinding;
  onSave: (id: number) => void;
  onFeedback: (id: number, verdict: "fit" | "not_fit") => void;
  showOtherHint: boolean;
};

export function SavedVideoSimilarFindingCard({ row, onSave, onFeedback, showOtherHint }: Props) {
  const metricsParts: string[] = [];
  const views = formatOptionalViews(row.views_count ?? null);
  if (views) metricsParts.push(views);
  if (row.published_text) metricsParts.push(row.published_text);

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
        {row.relevance_tier === "primary" && row.why_found ? (
          <p className="text-xs">
            <span className="text-muted-foreground">Похоже на ваш ролик: </span>
            {row.why_found}
          </p>
        ) : null}
        {metricsParts.length > 0 ? (
          <p className="text-xs text-muted-foreground">
            Показатели на YouTube: {metricsParts.join(" · ")} (без сравнения темпа с вашим роликом)
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">Показатели на YouTube: нет данных в выдаче</p>
        )}
        <p className="text-xs">Запрос: «{row.matched_query}»</p>
        {showOtherHint && row.other_reason ? (
          <p className="text-xs text-amber-200/90">Не в основном списке: {row.other_reason}</p>
        ) : null}
        <div className="mt-2 space-y-2 border-t border-border/60 pt-2">
          <div className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground">Оценить похожесть (только для этого списка)</p>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant={row.user_verdict === "fit" ? "default" : "secondary"}
                onClick={() => onFeedback(row.id, "fit")}
              >
                Подходит
              </Button>
              <Button
                type="button"
                size="sm"
                variant={row.user_verdict === "not_fit" ? "destructive" : "ghost"}
                onClick={() => onFeedback(row.id, "not_fit")}
              >
                Не подходит
              </Button>
            </div>
            {row.user_verdict ? (
              <p className="text-xs text-muted-foreground">
                Сохранено: {row.user_verdict === "fit" ? "подходит" : "не подходит"} (не добавляет ролик в
                «Сохранённые»)
              </p>
            ) : null}
          </div>
          <div className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground">Сохранить в исследования</p>
            <div className="flex flex-wrap items-center gap-2">
              <Link
                href={row.youtube_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center text-primary hover:underline"
              >
                YouTube <ExternalLink className="ml-1 h-3 w-3" />
              </Link>
              <Button
                type="button"
                size="sm"
                variant={row.saved_to_research ? "secondary" : "outline"}
                disabled={row.saved_to_research}
                onClick={() => onSave(row.id)}
              >
                {row.saved_to_research ? "Сохранено" : "Сохранить"}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </li>
  );
}
