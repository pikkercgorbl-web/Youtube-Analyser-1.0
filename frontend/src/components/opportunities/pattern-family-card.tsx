"use client";
import Link from "next/link";
import { WinnerFeedLink } from "@/components/opportunities/winner-feed-link";
import { buttonVariants } from "@/components/ui/button";
import {
  familyDetailHref,
  patternActivity,
  patternDetailHref,
  canonicalYoutubeUrl,
} from "@/lib/attention-format";
import type { AttentionPatternFamily } from "@/lib/attention-types";
import {
  familySectionBadge,
  isSearchCollectionFamily,
} from "@/lib/opportunity-family-presentation";
import { SaveFamilyButton } from "@/components/saved-research/save-family-button";
import { YoutubeThumb } from "./youtube-thumb";

/** @deprecated use API opportunity_presentation_tier */
export function isTopicCollection(family: AttentionPatternFamily) {
  return isSearchCollectionFamily(family);
}

export function PatternFamilyCard({
  family,
  runId,
  winnerTitlesById = {},
}: {
  family: AttentionPatternFamily;
  runId: string | null;
  winnerTitlesById?: Record<string, string>;
}) {
  const activity = patternActivity(family);
  const searchCollection = isSearchCollectionFamily(family);
  const badge = familySectionBadge(family);
  const basis =
    family.grouping_basis_label?.trim() ||
    "основание группировки уточняется в деталях";

  const bodyCopy = searchCollection
    ? "Это исследовательская подборка: общий запрос или метаданные не доказывают повторяемый формат."
    : family.opportunity_presentation_tier === "needs_review"
      ? "Есть объяснимое сходство заголовков у части роликов — сравните видео вручную перед выводами."
      : "Узкий признак в названиях совпал у нескольких каналов — сравните подачу и результат.";

  return (
    <article
      className="flex flex-col rounded-2xl border border-border bg-card p-5"
      data-testid="pattern-family-card"
      data-presentation-tier={family.opportunity_presentation_tier}
    >
      <p className="text-xs font-semibold uppercase tracking-wider text-primary">
        {badge}
      </p>
      <h3 className="mt-2 text-xl font-semibold">{family.label}</h3>
      <p
        className="mt-2 text-sm text-muted-foreground"
        data-testid="family-grouping"
      >
        {basis}
      </p>
      <div className="my-4 grid grid-cols-3 gap-2">
        {family.participating_video_ids.slice(0, 3).map((id, index) => (
          <a
            key={id}
            href={canonicalYoutubeUrl(id)}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`Открыть пример ${index + 1} по теме ${family.label}`}
          >
            <YoutubeThumb
              videoId={id}
              title={`Пример ${index + 1}`}
              className="aspect-video w-full rounded-lg"
            />
          </a>
        ))}
      </div>
      {family.feed_winner_video_ids.length > 0 ? (
        <div
          className="rounded-xl border border-border/80 bg-muted/30 px-3 py-2 text-sm"
          data-testid="family-feed-winners"
        >
          <p className="font-medium text-foreground">Winner в этой подборке</p>
          <ul className="mt-2 space-y-1">
            {family.feed_winner_video_ids.map((videoId) => (
              <li key={videoId}>
                <WinnerFeedLink
                  videoId={videoId}
                  className="text-primary hover:underline"
                >
                  {winnerTitlesById[videoId]?.trim() ||
                    `Видео ${videoId} в списке Winners`}
                </WinnerFeedLink>
              </li>
            ))}
          </ul>
          {searchCollection ? (
            <p className="mt-2 text-xs text-muted-foreground">
              Наличие Winner не делает всю группу подтверждённой возможностью.
            </p>
          ) : null}
        </div>
      ) : null}
      <p className="mt-3 text-sm" data-testid="pattern-channel-diversity">
        <strong className="text-lg">{family.channel_count}</strong> независимых
        каналов · <strong>{family.video_count}</strong> видео
      </p>
      <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
        {bodyCopy}
      </p>
      <div className="mt-auto flex flex-wrap gap-2 pt-5">
        <Link
          href={familyDetailHref(family.family_key)}
          className={buttonVariants({ variant: "secondary", size: "sm" })}
        >
          Изучить подборку →
        </Link>
        <SaveFamilyButton familyKey={family.family_key} runId={runId} />
      </div>
      <details className="mt-4 text-sm text-muted-foreground">
        <summary>Данные группировки</summary>
        <div className="mt-3 space-y-2">
          <p>{family.tier_reason}</p>
          {family.title_evidence_video_ids.length > 0 ? (
            <p data-testid="family-title-evidence">
              Видео со сходством заголовков:{" "}
              {family.title_evidence_video_ids.join(", ")}
            </p>
          ) : null}
          <p>
            {family.breakout_eligible_count} из {family.video_count} подходят
            для анализа Breakout. Это допуск к анализу, не число успешных
            роликов.
          </p>
          <p data-testid="pattern-activity">
            Количество видео:{" "}
            {activity.available ? activity.label : "Недостаточно истории"}{" "}
            (ранний период → предыдущие 24 ч → последние 24 ч).
          </p>
          <ul data-testid="family-member-patterns">
            {family.member_pattern_keys.map((key, i) => (
              <li key={key}>
                <Link
                  className="hover:text-primary"
                  href={patternDetailHref(key)}
                >
                  {family.member_labels[i] ?? "Исходная группа"}
                </Link>
              </li>
            ))}
          </ul>
          <p className="break-all text-xs">{family.family_key}</p>
          <p className="break-words text-xs" data-testid="family-flags">
            {family.quality_flags.join(" · ")}
          </p>
        </div>
      </details>
    </article>
  );
}
