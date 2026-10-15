"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import {
  ErrorState,
  LoadingState,
  PageShell,
  SectionPanel,
  UnavailableState,
} from "@/components/design-system";
import { buttonVariants } from "@/components/ui/button";
import { SaveVideoButton } from "@/components/saved-research/save-video-button";
import axios from "axios";

import { getAttentionVideo } from "@/lib/api";
import {
  canonicalYoutubeUrl,
  formatOptionalAge,
  formatOptionalSubscribers,
  formatOptionalViews,
  formatOptionalVph,
  humanReasonsForDisplay,
} from "@/lib/attention-format";
import type { AttentionVideoWinner } from "@/lib/attention-types";
import { surfaces } from "@/lib/design-system/layout";
import { cn } from "@/lib/utils";

import { ChannelBaselinePanel } from "./channel-baseline-panel";
import { AttentionSignalBadges } from "./signal-badges";
import { VideoDiscoveryKeywords } from "./video-discovery-keywords";
import { YoutubeThumb } from "./youtube-thumb";

function WinnerWhyBlock({ video }: { video: AttentionVideoWinner }) {
  const reasons = humanReasonsForDisplay(video.human_reasons);
  return (
    <SectionPanel title="Почему видео в Winners">
      <p className="text-sm text-muted-foreground">
        {video.breakout_rank != null
          ? `Место в рейтинге Radar: #${video.breakout_rank}. `
          : "Место в рейтинге Radar в снимке не указано. "}
        {video.acceleration_state === "accelerating"
          ? "Ускорение подтверждено серией измерений."
          : "Ранний сигнал по отдельному видео — повторяемость на канале проверяйте отдельно."}
      </p>
      {reasons.length > 0 ? (
        <ul className="mt-3 list-disc pl-4 text-sm text-muted-foreground">
          {reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-muted-foreground">
          Текстовые основания сигнала в снимке не сохранены — опирайтесь на метрики и
          сравнение с каналом ниже.
        </p>
      )}
      <AttentionSignalBadges
        className="mt-4"
        reasonCodes={video.reason_codes}
        accelerationState={video.acceleration_state}
        delayedOutcomeState={video.delayed_outcome_state}
        channelRelativeStatus={video.channel_relative_signal?.status}
      />
    </SectionPanel>
  );
}

function WinnerChannelCompareBlock({ video }: { video: AttentionVideoWinner }) {
  return (
    <SectionPanel title="Сравнение с обычными результатами канала">
      {video.channel_relative_signal ? (
        <ChannelBaselinePanel rel={video.channel_relative_signal} />
      ) : (
        <p className="text-sm text-muted-foreground" data-testid="baseline-unavailable">
          Для этого видео в текущем снимке нет сравнения с медианой канала — недостаточно
          сопоставимых роликов или baseline ещё не рассчитан.
        </p>
      )}
    </SectionPanel>
  );
}

function WinnerDiscoveryBlock({ video }: { video: AttentionVideoWinner }) {
  return (
    <SectionPanel title="По каким поисковым запросам Radar нашёл видео">
      <VideoDiscoveryKeywords
        videoId={video.video_id}
        keywords={video.discovery_keywords ?? []}
      />
    </SectionPanel>
  );
}

export function OpportunityWinnerDetailView({ videoId }: { videoId: string }) {
  const [loadState, setLoadState] = useState<"loading" | "error" | "ready" | "missing">(
    "loading",
  );
  const [errorMessage, setErrorMessage] = useState("");
  const [video, setVideo] = useState<AttentionVideoWinner | null>(null);

  const load = useCallback(async () => {
    setLoadState("loading");
    try {
      const data = await getAttentionVideo(videoId);
      if (data.data_source === "unavailable" || !data.video) {
        setVideo(null);
        setLoadState("missing");
        return;
      }
      setVideo(data.video);
      setLoadState("ready");
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 404) {
        setLoadState("missing");
        return;
      }
      setErrorMessage(
        error instanceof Error ? error.message : "Не удалось загрузить видео",
      );
      setLoadState("error");
    }
  }, [videoId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loadState === "loading") {
    return (
      <PageShell>
        <LoadingState title="Загрузка видео…" />
      </PageShell>
    );
  }

  if (loadState === "error") {
    return (
      <PageShell>
        <ErrorState title="Ошибка загрузки" description={errorMessage} onRetry={() => void load()} />
      </PageShell>
    );
  }

  if (loadState === "missing" || !video) {
    return (
      <PageShell>
        <Link
          href="/opportunities"
          className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "mb-4 w-fit")}
        >
          <ArrowLeft className="mr-2 h-4 w-4" aria-hidden />
          К списку Winners
        </Link>
        <UnavailableState
          title="Видео нет в текущем снимке Winners"
          description="Возможно, ролик выпал из рейтинга или снимок ещё не обновлён. Вернитесь к списку и выберите другое видео."
        />
      </PageShell>
    );
  }

  const youtubeHref = canonicalYoutubeUrl(video.video_id, video.youtube_url);
  const title = video.title || "Видео без названия";

  return (
    <PageShell>
      <Link
        href="/opportunities"
        className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "mb-4 w-fit")}
        data-testid="winner-detail-back"
      >
        <ArrowLeft className="mr-2 h-4 w-4" aria-hidden />
        К списку Winners
      </Link>

      <article className={cn(surfaces.section, "overflow-hidden rounded-2xl")}>
        <a
          href={youtubeHref}
          target="_blank"
          rel="noopener noreferrer"
          className="relative block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          aria-label={`Открыть «${title}» на YouTube`}
        >
          <YoutubeThumb
            videoId={video.video_id}
            title={title}
            className="aspect-video w-full bg-muted"
          />
          <span className="absolute bottom-3 right-3 rounded-lg bg-black/80 px-3 py-1 text-sm text-white">
            {formatOptionalAge(video.age_hours) ?? "Возраст неизвестен"}
          </span>
        </a>
        <div className="space-y-6 p-5 md:p-6">
          <div className="space-y-2">
            <a
              href={youtubeHref}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xl font-semibold leading-snug hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              {title}
            </a>
            <p className="text-sm text-muted-foreground">
              {video.channel_title || "Канал неизвестен"} ·{" "}
              {formatOptionalSubscribers(video.subscribers) ?? "—"} подписчиков
            </p>
            <dl className="grid grid-cols-2 gap-4 border-y border-border/60 py-4 sm:max-w-md">
              <div>
                <dt className="text-xs text-muted-foreground">Просмотры</dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums">
                  {formatOptionalViews(video.views) ?? "—"}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">В среднем за час</dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums text-primary">
                  {formatOptionalVph(video.vph) ?? "—"}
                </dd>
              </div>
            </dl>
          </div>

          <div className="flex flex-wrap gap-3">
            <SaveVideoButton videoId={video.video_id} />
            <Link
              href={`/monitoring/videos/${encodeURIComponent(video.video_id)}`}
              className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
            >
              Динамика видео
            </Link>
          </div>

          <div className="space-y-5">
            <WinnerWhyBlock video={video} />
            <WinnerChannelCompareBlock video={video} />
            <WinnerDiscoveryBlock video={video} />
          </div>
        </div>
      </article>
    </PageShell>
  );
}
