"use client";



import Image from "next/image";

import Link from "next/link";



import { SaveVideoButton } from "@/components/saved-research/save-video-button";

import { Card, CardContent } from "@/components/ui/card";

import type { ManualSearchVideoContextItem } from "@/lib/api";

import { buildChannelSingleAnalysisUrl } from "@/lib/channel-single-analysis-url";
import { formatViewsAndAgeLine, parseDurationSeconds } from "@/lib/manual-search-published-format";
import { buttonVariants } from "@/components/ui/button";

import {

  manualSearchSubscriberSkeleton,

  resolveManualSearchSubscribers,

} from "@/lib/manual-search-subscribers";

import type { EnrichedVideoModel } from "@/lib/types";

import { cn, formatCompactNumber, youtubeThumbnail, youtubeVideoUrl } from "@/lib/utils";



type Props = {

  item: EnrichedVideoModel;

  ctx: ManualSearchVideoContextItem | undefined;

  metricsPending: boolean;

  onSaved: (savedId: number) => void;

};



export function ManualSearchVideoCard({ item, ctx, metricsPending, onSaved }: Props) {

  const videoId = item.video.video_id;

  const title = item.video.title?.trim() || "Без названия";

  const channelTitle = item.video.channel_title?.trim() || "Неизвестный канал";

  const thumbnailUrl = item.video.thumbnail_url || youtubeThumbnail(videoId);

  const channelAvatarUrl = item.channel.channel_avatar_url || item.video.channel_avatar_url || "";

  const durationText = item.video.duration_text?.trim();

  const statsLine = formatViewsAndAgeLine(item.video.views_count, item.video.published_text);

  const subscribers = resolveManualSearchSubscribers(item);

  const showSubscriberSkeleton = manualSearchSubscriberSkeleton(item, metricsPending);



  return (

    <Card className="overflow-hidden border-border/60 transition-shadow hover:shadow-lg hover:shadow-primary/10">

      <a

        href={youtubeVideoUrl(videoId)}

        target="_blank"

        rel="noopener noreferrer"

        className="group block"

      >

        <div className="relative aspect-video overflow-hidden bg-muted">

          <Image

            src={thumbnailUrl}

            alt=""

            fill

            unoptimized

            className="object-cover transition-transform duration-300 group-hover:scale-[1.02]"

            sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw"

          />

          {durationText && parseDurationSeconds(durationText) > 0 ? (

            <span className="absolute bottom-2 right-2 rounded bg-black/80 px-1.5 py-0.5 text-xs font-medium text-white">

              {durationText}

            </span>

          ) : null}

        </div>

      </a>



      <CardContent className="space-y-2.5 p-4">

        <a

          href={youtubeVideoUrl(videoId)}

          target="_blank"

          rel="noopener noreferrer"

          title={title}

          className="line-clamp-3 text-base font-semibold leading-snug hover:text-primary"

        >

          {title}

        </a>



        <div className="flex items-start gap-2 min-w-0">

          {channelAvatarUrl ? (

            <Image

              src={channelAvatarUrl}

              alt=""

              width={28}

              height={28}

              unoptimized

              className="h-7 w-7 shrink-0 rounded-full object-cover ring-1 ring-border/60"

            />

          ) : (

            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold uppercase text-muted-foreground ring-1 ring-border/60">

              {channelTitle.slice(0, 1) || "?"}

            </div>

          )}

          <div className="min-w-0 flex-1 space-y-0.5">

            <p className="truncate text-sm text-muted-foreground">{channelTitle}</p>

            {subscribers !== null ? (

              <p className="text-sm leading-snug text-foreground/75 [overflow-wrap:anywhere]">

                <span className="font-medium text-foreground/90">

                  {formatCompactNumber(subscribers)}

                </span>{" "}

                <span className="font-normal">подписчиков</span>

              </p>

            ) : showSubscriberSkeleton ? (

              <div

                className="h-3 w-28 max-w-full animate-pulse rounded bg-muted"

                aria-label="Загрузка числа подписчиков"

                role="status"

              />

            ) : null}

          </div>

        </div>



        {statsLine ? <p className="text-sm text-foreground/90">{statsLine}</p> : null}



        <div className="flex flex-wrap items-center gap-2 pt-0.5">

          {ctx?.in_corpus ? (

            <span className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">

              Уже в базе

            </span>

          ) : null}

          {ctx?.saved_video_id != null ? (

            <Link

              href={`/saved/videos/${ctx.saved_video_id}`}

              className="rounded-md bg-secondary px-2 py-0.5 text-xs text-secondary-foreground"

            >

              Сохранено

            </Link>

          ) : null}

          {ctx && ctx.snapshot_count > 0 ? (

            <Link

              href={`/monitoring/videos/${videoId}`}

              className="text-xs text-primary underline-offset-2 hover:underline"

            >

              История snapshots

            </Link>

          ) : null}

        </div>



        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          {item.video.channel_id?.trim() ? (
            <Link
              href={buildChannelSingleAnalysisUrl({
                channelId: item.video.channel_id.trim(),
                focusVideoId: videoId,
              })}
              className={cn(
                buttonVariants({ variant: "outline", size: "sm" }),
                "w-full sm:w-auto",
              )}
            >
              Анализ канала
            </Link>
          ) : null}
          <SaveVideoButton
            videoId={videoId}
            fromManualSearch
            skipInitialCheck
            initialSavedId={ctx?.saved_video_id ?? null}
            onSaved={onSaved}
          />
        </div>

      </CardContent>

    </Card>

  );

}

