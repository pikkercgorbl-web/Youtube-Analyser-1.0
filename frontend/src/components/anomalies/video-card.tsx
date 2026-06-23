"use client";

import Image from "next/image";
import { Eye, MessageCircle, ThumbsUp, Users } from "lucide-react";
import type { ExtendedSearchVideoItem } from "@/lib/types";
import {
  cn,
  formatDuration,
  formatNumber,
  formatPercent,
  viralityColor,
  youtubeThumbnail,
  youtubeVideoUrl,
} from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

interface VideoCardProps {
  video: ExtendedSearchVideoItem;
}

export function VideoCard({ video }: VideoCardProps) {
  const ratio = video.channel_subscribers_count
    ? video.views_count / video.channel_subscribers_count
    : video.views_count;

  return (
    <Card className="group overflow-hidden transition-all hover:border-primary/40 hover:shadow-lg hover:shadow-primary/5">
      <a href={youtubeVideoUrl(video.video_id)} target="_blank" rel="noopener noreferrer">
        <div className="relative aspect-video overflow-hidden bg-muted">
          <Image
            src={youtubeThumbnail(video.video_id)}
            alt={video.title}
            fill
            className="object-cover transition-transform duration-300 group-hover:scale-105"
            sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw"
          />
          <div className="absolute bottom-2 right-2 rounded bg-black/80 px-1.5 py-0.5 text-xs font-medium">
            {formatDuration(video.duration_seconds)}
          </div>
          <div
            className={cn(
              "absolute left-2 top-2 rounded-lg bg-gradient-to-r px-3 py-1.5 text-sm font-bold text-white shadow-lg",
              viralityColor(video.virality_percent),
            )}
          >
            Коэффициент вирусности: {formatPercent(video.virality_percent, 0)}
          </div>
        </div>
      </a>

      <CardContent className="space-y-3 p-4">
        <a
          href={youtubeVideoUrl(video.video_id)}
          target="_blank"
          rel="noopener noreferrer"
          className="line-clamp-2 text-sm font-semibold leading-snug hover:text-primary"
        >
          {video.title}
        </a>

        <p className="text-xs text-muted-foreground">{video.channel_title}</p>

        <div className="grid grid-cols-2 gap-2 text-xs">
          <Stat icon={Eye} label="Просмотры" value={formatNumber(video.views_count)} />
          <Stat icon={Users} label="Подписчики" value={formatNumber(video.channel_subscribers_count)} />
          <Stat icon={ThumbsUp} label="Лайки" value={formatNumber(video.likes_count)} />
          <Stat icon={MessageCircle} label="Комменты" value={formatNumber(video.comments_count)} />
        </div>

        <div className="rounded-lg border border-border/60 bg-secondary/30 p-3">
          <p className="text-xs text-muted-foreground">Соотношение просмотров к подписчикам</p>
          <div className="mt-1 flex items-baseline justify-between gap-2">
            <span className="text-lg font-bold text-emerald-400">{ratio.toFixed(1)}×</span>
            <Badge variant="success">{formatPercent(video.virality_percent, 0)} от базы</Badge>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-2 rounded-md bg-muted/40 px-2 py-1.5">
      <Icon className="h-3.5 w-3.5 text-muted-foreground" />
      <div>
        <p className="text-[10px] text-muted-foreground">{label}</p>
        <p className="font-medium">{value}</p>
      </div>
    </div>
  );
}
