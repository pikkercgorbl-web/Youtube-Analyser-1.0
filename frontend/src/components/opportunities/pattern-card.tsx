"use client";

import Link from "next/link";
import { Bookmark } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import {
  groupingSourceLabel,
  groupingSourceShort,
  patternActivity,
  patternDetailHref,
} from "@/lib/attention-format";
import type { AttentionPattern } from "@/lib/attention-types";
import { surfaces } from "@/lib/design-system/layout";
import { savedTopicAffordance } from "@/lib/saved-topics";
import { cn } from "@/lib/utils";

import { HumanReasonsList } from "./signal-badges";

export function PatternCard({
  pattern,
  runId,
}: {
  pattern: AttentionPattern;
  runId: string | null;
}) {
  const activity = patternActivity(pattern);
  const save = savedTopicAffordance({ familyKey: pattern.pattern_key, runId });
  return (
    <article className={cn(surfaces.sectionMuted, "flex flex-col p-4")} data-testid="pattern-card">
      <p className="text-sm font-semibold leading-snug">{pattern.label}</p>
      <p className="mt-1 text-xs text-muted-foreground" data-testid="pattern-grouping">
        {groupingSourceLabel(pattern.kind)}
      </p>
      <p className="sr-only">{groupingSourceShort(pattern.kind)}</p>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <div data-testid="pattern-channel-diversity">
          <p className="text-lg font-semibold tabular-nums">{pattern.channel_count}</p>
          <p className="text-xs text-muted-foreground">независимых каналов</p>
        </div>
        <div>
          <p className="text-lg font-semibold tabular-nums">{pattern.video_count}</p>
          <p className="text-xs text-muted-foreground">видео</p>
        </div>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <div>
          <dt className="inline">Keywords: </dt>
          <dd className="inline">{pattern.keyword_count}</dd>
        </div>
        <div>
          <dt className="inline">Выборка Breakout: </dt>
          <dd className="inline">{pattern.breakout_video_count} видео входят в выборку Breakout</dd>
        </div>
        <div className="col-span-2" data-testid="pattern-activity">
          <dt>Активность по периодам</dt>
          <dd>{activity.available ? activity.label : "Недостаточно истории"}</dd>
        </div>
        {pattern.first_seen_at ? (
          <div className="col-span-2">
            first_seen: {new Date(pattern.first_seen_at).toLocaleString("ru-RU")}
          </div>
        ) : null}
        {pattern.latest_seen_at ? (
          <div className="col-span-2">
            latest_seen: {new Date(pattern.latest_seen_at).toLocaleString("ru-RU")}
          </div>
        ) : null}
      </dl>
      <HumanReasonsList reasons={pattern.human_reasons} />
      <div className="mt-auto flex gap-2 pt-4">
        <Link
          href={patternDetailHref(pattern.pattern_key)}
          className={buttonVariants({ variant: "secondary", size: "sm" })}
        >
          Открыть
        </Link>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled
          title={save.hint}
          aria-label={save.hint}
          data-testid="save-pattern"
        >
          <Bookmark className="h-3.5 w-3.5" />
          Сохранить
        </Button>
      </div>
    </article>
  );
}
