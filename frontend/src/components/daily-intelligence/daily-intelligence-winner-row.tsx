"use client";

import Link from "next/link";

import { dailyIntelligenceWinnerDetailHref } from "@/lib/daily-intelligence-routes";
import type { DailyIntelligenceWinnerListItem } from "@/lib/daily-intelligence-types";

import { DailyIntelligenceOutcomeCoverageBadge } from "./daily-intelligence-outcome-coverage-badge";
import { DailyIntelligenceWinnerThumb } from "./daily-intelligence-winner-thumb";

export function DailyIntelligenceWinnerRow({
  row,
  reportDate,
  outcomeCoverage,
  outcomeCoveragePending,
}: {
  row: DailyIntelligenceWinnerListItem;
  reportDate: string;
  outcomeCoverage?: { coverage_category: string; outcome_window_phase: string };
  outcomeCoveragePending?: boolean;
}) {
  return (
    <tr className="border-t border-border/60" data-testid="di-winner-row">
      <td className="px-3 py-2 tabular-nums text-muted-foreground align-top">{row.rank}</td>
      <td className="px-3 py-2 align-top min-w-[200px]">
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
            <p className="text-xs text-muted-foreground font-mono truncate mt-0.5">{row.video_id}</p>
            <Link
              href={dailyIntelligenceWinnerDetailHref(reportDate, row.video_id)}
              className="text-xs text-primary hover:underline mt-1 inline-block"
              data-testid="di-winner-evidence-link"
            >
              История и доказательства
            </Link>
          </div>
        </div>
      </td>
      <td className="px-3 py-2 text-muted-foreground line-clamp-3 align-top max-w-[180px]">
        {row.channel_title}
      </td>
      <td className="px-3 py-2 text-xs align-top">
        {row.discovery_provenance_available === true
          ? "Есть"
          : row.discovery_provenance_available === false
            ? "Нет"
            : "—"}
      </td>
      <td className="px-3 py-2 text-xs align-top">{row.is_repeat_in_prior_reports ? "Да" : "Нет"}</td>
      <td className="px-3 py-2 text-xs align-top">
        {outcomeCoveragePending ? (
          <span className="text-muted-foreground">…</span>
        ) : outcomeCoverage ? (
          <DailyIntelligenceOutcomeCoverageBadge
            category={outcomeCoverage.coverage_category}
            phase={outcomeCoverage.outcome_window_phase}
            compact
          />
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </td>
    </tr>
  );
}
