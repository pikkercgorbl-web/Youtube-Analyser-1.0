"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  Disclosure,
  ErrorState,
  PageShell,
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
import {
  readStashedAttentionMeta,
  readStashedWinner,
  stashWinnerForDetail,
} from "@/lib/opportunity-winner-cache";
import {
  buildWinnerInsightBlocks,
  formatWinnerSnapshotContextLine,
} from "@/lib/opportunity-winner-presentation";
import { surfaces } from "@/lib/design-system/layout";
import { cn } from "@/lib/utils";

import { ChannelBaselinePanel } from "./channel-baseline-panel";
import { OpportunityWinnerDetailSkeleton } from "./opportunity-winner-detail-skeleton";
import { AttentionSignalBadges } from "./signal-badges";
import { VideoDiscoveryKeywords } from "./video-discovery-keywords";
import { WinnerInsightBlocks } from "./winner-insight-blocks";
import { YoutubeThumb } from "./youtube-thumb";

export function OpportunityWinnerDetailView({ videoId }: { videoId: string }) {
  const stashed = useMemo(() => readStashedWinner(videoId), [videoId]);
  const [loadState, setLoadState] = useState<"loading" | "error" | "ready" | "missing">(
    stashed ? "ready" : "loading",
  );
  const [errorMessage, setErrorMessage] = useState("");
  const [video, setVideo] = useState<AttentionVideoWinner | null>(stashed);
  const [computedAt, setComputedAt] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(Boolean(stashed));

  const load = useCallback(async () => {
    if (!stashed) {
      setLoadState("loading");
    } else {
      setSyncing(true);
    }
    try {
      const data = await getAttentionVideo(videoId);
      setComputedAt(data.computed_at);
      if (data.data_source === "unavailable" || !data.video) {
        setVideo(null);
        setLoadState("missing");
        return;
      }
      setVideo(data.video);
      stashWinnerForDetail(data.video);
      setLoadState("ready");
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 404) {
        if (!stashed) {
          setLoadState("missing");
        }
        setSyncing(false);
        return;
      }
      if (stashed) {
        setSyncing(false);
        return;
      }
      setErrorMessage(
        error instanceof Error ? error.message : "Не удалось загрузить видео",
      );
      setLoadState("error");
    } finally {
      setSyncing(false);
    }
  }, [videoId, stashed]);

  useEffect(() => {
    void load();
  }, [load]);

  const snapshotContextLine = useMemo(() => {
    const meta = readStashedAttentionMeta();
    return formatWinnerSnapshotContextLine({
      computedAt: computedAt ?? meta?.computed_at ?? null,
      windowHours: meta?.window_hours ?? null,
      windowStart: meta?.window_start ?? null,
      windowEnd: meta?.window_end ?? null,
    });
  }, [computedAt]);

  if (loadState === "loading") {
    return <OpportunityWinnerDetailSkeleton />;
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
  const insightBlocks = buildWinnerInsightBlocks(video);
  const humanReasons = humanReasonsForDisplay(video.human_reasons);

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

      {syncing ? (
        <p className="mb-2 text-xs text-muted-foreground" aria-live="polite">
          Обновляем данные снимка…
        </p>
      ) : null}

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
        <div className="space-y-5 p-5 md:p-6">
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
                <dt className="text-xs text-muted-foreground">Просмотры (снимок)</dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums">
                  {formatOptionalViews(video.views) ?? "—"}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">VPH (снимок)</dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums text-primary">
                  {formatOptionalVph(video.vph) ?? "—"}
                </dd>
              </div>
            </dl>
          </div>

          <p className="text-xs leading-relaxed text-muted-foreground" data-testid="winner-snapshot-context">
            {snapshotContextLine}
          </p>

          <WinnerInsightBlocks blocks={insightBlocks} />

          <div className="flex flex-wrap gap-3">
            <SaveVideoButton videoId={video.video_id} />
            <Link
              href={`/monitoring/videos/${encodeURIComponent(video.video_id)}`}
              className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
            >
              Динамика видео
            </Link>
          </div>

          <Disclosure summary="Как рассчитано">
            <div className="space-y-4 text-sm text-muted-foreground">
              {video.breakout_rank != null ? (
                <p>
                  Рейтинг breakout_v1 в окне Attention: #{video.breakout_rank}
                  {video.breakout_eligible ? " · eligible" : ""}.
                </p>
              ) : null}
              <AttentionSignalBadges
                treatAsWinner
                reasonCodes={video.reason_codes}
                accelerationState={video.acceleration_state}
                delayedOutcomeState={video.delayed_outcome_state}
                channelRelativeStatus={video.channel_relative_signal?.status}
              />
              {humanReasons.length > 0 ? (
                <ul className="list-disc pl-4">
                  {humanReasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              ) : (
                <p>Текстовые reason codes в снимке не сохранены.</p>
              )}
              {video.reason_codes.length > 0 ? (
                <p className="font-mono text-xs">reason_codes: {video.reason_codes.join(", ")}</p>
              ) : null}
              {video.channel_relative_signal ? (
                <ChannelBaselinePanel rel={video.channel_relative_signal} />
              ) : (
                <p data-testid="baseline-unavailable">
                  Сравнение с каналом в снимке отсутствует.
                </p>
              )}
              <p className="text-xs">
                video_id: <span className="font-mono">{video.video_id}</span>
                {video.channel_id ? (
                  <>
                    {" "}
                    · channel_id: <span className="font-mono">{video.channel_id}</span>
                  </>
                ) : null}
              </p>
            </div>
          </Disclosure>

          <Disclosure summary="Где найдено">
            <VideoDiscoveryKeywords
              videoId={video.video_id}
              keywords={video.discovery_keywords ?? []}
            />
          </Disclosure>
        </div>
      </article>
    </PageShell>
  );
}
