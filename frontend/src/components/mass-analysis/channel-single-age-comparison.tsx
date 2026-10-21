"use client";

import Image from "next/image";

import { CHANNEL_SINGLE_COMPARE_HINT, CHANNEL_SINGLE_COMPARE_METHOD_NOTE } from "@/lib/channel-single-analysis-copy";
import type { ChannelSingleFocusComparison } from "@/lib/types";
import {
  formatAgeHoursLabel,
  formatAgeWindowLabel,
} from "@/lib/channel-single-analysis-overview";
import { formatNumber, youtubeThumbnail } from "@/lib/utils";

export function ChannelSingleAgeComparison({
  comparison,
  busy,
  enrichError,
  hasFocus = false,
}: {
  comparison: ChannelSingleFocusComparison | undefined;
  busy: boolean;
  enrichError: string | null;
  hasFocus?: boolean;
}) {
  if (busy) {
    return (
      <section className="rounded-lg border border-border/60 bg-card p-4 text-sm">
        <h3 className="mb-2 text-base font-semibold">Сравнение по возрасту</h3>
        <p className="animate-pulse text-muted-foreground">Считаем сравнение…</p>
      </section>
    );
  }

  if (!comparison) {
    return (
      <section className="rounded-lg border border-border/60 bg-card p-4 text-sm">
        <h3 className="mb-2 text-base font-semibold">Сравнение по возрасту</h3>
        <p className="text-muted-foreground">{CHANNEL_SINGLE_COMPARE_HINT}</p>
      </section>
    );
  }

  const showPeerDetails =
    comparison.searched_age_low_hours != null && comparison.searched_age_high_hours != null;
  const insufficientPeers = comparison.status === "insufficient_peers";
  const ok = comparison.status === "ok" && comparison.multiplier != null;

  return (
    <section className="rounded-lg border border-border/60 bg-card p-4 text-sm">
      <h3 className="mb-3 text-base font-semibold">Сравнение по возрасту</h3>
      <div className="space-y-3">
        {!hasFocus && comparison.status === "no_focus" ? (
          <p className="text-muted-foreground">{CHANNEL_SINGLE_COMPARE_HINT}</p>
        ) : null}
        {showPeerDetails ? (
          <p className="text-muted-foreground">
            Искали обычные ролики возрастом{" "}
            {formatAgeWindowLabel(
              comparison.searched_age_low_hours!,
              comparison.searched_age_high_hours!,
            )}
            {comparison.focus_age_hours != null
              ? ` (выбранное ~${formatAgeHoursLabel(comparison.focus_age_hours)})`
              : ""}
            .
          </p>
        ) : null}

        {ok ? (
          <>
            <p className="font-medium">{comparison.message}</p>
            <ul className="list-inside list-disc text-muted-foreground">
              <li>Медиана просмотров группы: {formatNumber(comparison.median_views ?? 0)}</li>
              <li>Роликов в группе: {comparison.peer_count}</li>
              {comparison.peer_age_min_hours != null && comparison.peer_age_max_hours != null ? (
                <li>
                  Возраст найденных: {formatAgeHoursLabel(comparison.peer_age_min_hours)} –{" "}
                  {formatAgeHoursLabel(comparison.peer_age_max_hours)}
                </li>
              ) : null}
            </ul>
          </>
        ) : (
          <>
            <p className="text-foreground/90">{comparison.message}</p>
            {insufficientPeers ? (
              <p className="text-muted-foreground">
                Коэффициент относительно медианы не показываем — в выборке канала недостаточно
                обычных роликов в окне возраста (нужно минимум 5).
              </p>
            ) : null}
            {comparison.peer_count > 0 ? (
              <p className="text-muted-foreground">
                Найдено сопоставимых по возрасту: {comparison.peer_count}.
              </p>
            ) : null}
          </>
        )}

        {comparison.age_peer_samples.length > 0 ? (
          <ul className="divide-y divide-border/60 rounded-md border border-border/50">
            {comparison.age_peer_samples.map((sample) => {
              const thumb = sample.thumbnail_url || youtubeThumbnail(sample.video_id);
              return (
                <li key={sample.video_id} className="flex gap-3 p-2">
                  <div className="relative h-12 w-20 shrink-0 overflow-hidden rounded bg-muted">
                    <Image src={thumb} alt="" fill unoptimized className="object-cover" sizes="80px" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="line-clamp-2 text-xs font-medium">
                      {sample.title || sample.video_id}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {formatNumber(sample.views_count)} просмотров · возраст ~{" "}
                      {formatAgeHoursLabel(sample.age_hours)}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        ) : null}

        <p className="text-xs text-muted-foreground">{CHANNEL_SINGLE_COMPARE_METHOD_NOTE}</p>
        <p className="text-xs text-muted-foreground">{comparison.disclaimer}</p>
        {enrichError ? (
          <p className="text-xs text-amber-600 dark:text-amber-500">{enrichError}</p>
        ) : null}
      </div>
    </section>
  );
}
