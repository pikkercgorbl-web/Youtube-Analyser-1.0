"use client";

import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import {
  diWinnerListRankLabel,
  diWinnerListReasonSummary,
} from "@/lib/daily-intelligence-presentation";
import { dailyIntelligenceWinnerDetailHref } from "@/lib/daily-intelligence-routes";
import type { DailyIntelligenceWinnerListItem } from "@/lib/daily-intelligence-types";
import { cn } from "@/lib/utils";

import { DailyIntelligenceWinnerThumb } from "./daily-intelligence-winner-thumb";

export function DailyIntelligenceWinnerRow({
  row,
  reportDate,
}: {
  row: DailyIntelligenceWinnerListItem;
  reportDate: string;
}) {
  return (
    <tr className="border-t border-border/60" data-testid="di-winner-row">
      <td className="px-3 py-3 align-top min-w-[220px]">
        <div className="flex gap-3 min-w-0">
          <DailyIntelligenceWinnerThumb
            videoId={row.video_id}
            title={row.title}
            href={row.youtube_url}
          />
          <div className="min-w-0 flex-1">
            <a
              href={row.youtube_url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium hover:text-primary line-clamp-3 break-words"
            >
              {row.title}
            </a>
            <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">{row.channel_title}</p>
            {row.is_repeat_in_prior_reports ? (
              <p className="text-xs text-amber-200/90 mt-1">Уже было в более ранних отчётах</p>
            ) : null}
          </div>
        </div>
      </td>
      <td className="px-3 py-3 text-sm align-top max-w-[240px]">
        <p className="font-medium leading-snug" data-testid="di-winner-reason-summary">
          {diWinnerListReasonSummary(row.reason_summary)}
        </p>
      </td>
      <td className="px-3 py-3 text-sm tabular-nums align-top whitespace-nowrap">
        {diWinnerListRankLabel(row.rank)}
      </td>
      <td className="px-3 py-3 align-top">
        <Link
          href={dailyIntelligenceWinnerDetailHref(reportDate, row.video_id)}
          className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
          data-testid="di-winner-evidence-link"
        >
          Карточка
        </Link>
      </td>
    </tr>
  );
}
