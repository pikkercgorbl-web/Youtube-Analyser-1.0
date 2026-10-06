"use client";

import { useState } from "react";
import Link from "next/link";

import { Button, buttonVariants } from "@/components/ui/button";
import {
  familyDetailHref,
  groupingSourceLabel,
  patternActivity,
  patternDetailHref,
} from "@/lib/attention-format";
import type { AttentionPatternFamily } from "@/lib/attention-types";
import { surfaces } from "@/lib/design-system/layout";
import { SaveTopicButton } from "@/components/saved-topics/save-topic-button";
import { cn } from "@/lib/utils";

export function PatternFamilyCard({
  family,
  runId,
}: {
  family: AttentionPatternFamily;
  runId: string | null;
}) {
  const [showMembers, setShowMembers] = useState(false);
  const activity = patternActivity(family);
  const variants = family.member_labels.length;
  return (
    <article className={cn(surfaces.sectionMuted, "flex flex-col p-4")} data-testid="pattern-family-card">
      <p className="text-sm font-semibold leading-snug">{family.label}</p>
      <p className="mt-1 text-xs text-muted-foreground" data-testid="family-grouping">
        {groupingSourceLabel(family.family_kind)}
      </p>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <div data-testid="pattern-channel-diversity">
          <p className="text-lg font-semibold tabular-nums">{family.channel_count}</p>
          <p className="text-xs text-muted-foreground">независимых каналов</p>
        </div>
        <div>
          <p className="text-lg font-semibold tabular-nums">{family.video_count}</p>
          <p className="text-xs text-muted-foreground">уникальных видео</p>
        </div>
      </div>
      {variants > 1 ? (
        <p className="mt-2 text-xs text-muted-foreground">{variants} связанных вариантов паттерна</p>
      ) : null}
      <div className="mt-2 flex flex-wrap gap-1" data-testid="family-flags">
        {family.quality_flags.map((flag) => (
          <span key={flag} className="rounded-full border border-border/60 px-2 py-0.5 text-[10px]">
            {flag}
          </span>
        ))}
        {family.support_sources.map((src) => (
          <span key={src} className="rounded-full border border-sky-500/30 px-2 py-0.5 text-[10px] text-sky-200">
            {src}
          </span>
        ))}
      </div>
      <p className="mt-2 text-xs text-muted-foreground" data-testid="pattern-activity">
        Активность по периодам: {activity.available ? activity.label : "Недостаточно истории"}
      </p>
      <p className="text-xs text-muted-foreground">
        {family.breakout_eligible_count} из {family.video_count} видео — подходят для анализа Breakout (не топ Winners)
      </p>
      <div className="mt-auto flex flex-wrap gap-2 pt-4">
        <Link
          href={familyDetailHref(family.family_key)}
          className={buttonVariants({ variant: "secondary", size: "sm" })}
        >
          Открыть
        </Link>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setShowMembers((value) => !value)}
          data-testid="show-source-patterns"
        >
          {showMembers ? "Скрыть исходные паттерны" : "Показать исходные паттерны"}
        </Button>
        <SaveTopicButton familyKey={family.family_key} runId={runId} />
      </div>
      {showMembers ? (
        <ul className="mt-3 space-y-1 text-xs" data-testid="family-member-patterns">
          {family.member_pattern_keys.map((key, index) => (
            <li key={key}>
              <Link href={patternDetailHref(key)} className="text-primary hover:underline">
                {family.member_labels[index] ?? key}
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
          {family.member_labels.join(" · ")}
        </p>
      )}
    </article>
  );
}
