"use client";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import {
  familyDetailHref,
  groupingSourceLabel,
  patternActivity,
  patternDetailHref,
  canonicalYoutubeUrl,
} from "@/lib/attention-format";
import type { AttentionPatternFamily } from "@/lib/attention-types";
import { SaveTopicButton } from "@/components/saved-topics/save-topic-button";
import { YoutubeThumb } from "./youtube-thumb";

export function isTopicCollection(family: AttentionPatternFamily) {
  return (
    ["keyword", "topic", "keyword_provenance", "video_topic"].includes(
      family.family_kind,
    ) ||
    family.quality_flags.includes("broad_keyword_group") ||
    family.quality_flags.includes("keyword_only")
  );
}
export function PatternFamilyCard({
  family,
  runId,
}: {
  family: AttentionPatternFamily;
  runId: string | null;
}) {
  const activity = patternActivity(family);
  const broad = isTopicCollection(family);
  return (
    <article
      className="flex flex-col rounded-2xl border border-border bg-card p-5"
      data-testid="pattern-family-card"
    >
      <p className="text-xs font-semibold uppercase tracking-wider text-primary">
        {broad ? "Подборка по теме" : "Сходство заголовков"}
      </p>
      <h3 className="mt-2 text-xl font-semibold">{family.label}</h3>
      <p
        className="mt-2 text-sm text-muted-foreground"
        data-testid="family-grouping"
      >
        {groupingSourceLabel(family.family_kind)}
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
      <p className="text-sm" data-testid="pattern-channel-diversity">
        <strong className="text-lg">{family.channel_count}</strong> независимых
        каналов · <strong>{family.video_count}</strong> видео
      </p>
      <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
        {broad
          ? "Общий поисковый запрос или тема. Сравните ролики, чтобы найти конкретный приём."
          : "Похожие фразы встречаются на разных каналах. Сравните подачу и результаты роликов."}{" "}
        Совпадение не доказывает повторяемый успех.
      </p>
      <div className="mt-auto flex flex-wrap gap-2 pt-5">
        <Link
          href={familyDetailHref(family.family_key)}
          className={buttonVariants({ variant: "secondary", size: "sm" })}
        >
          Изучить подборку →
        </Link>
        <SaveTopicButton familyKey={family.family_key} runId={runId} />
      </div>
      <details className="mt-4 text-sm text-muted-foreground">
        <summary>Данные группировки</summary>
        <div className="mt-3 space-y-2">
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
