"use client";

import type { WinnerInsightBlock } from "@/lib/opportunity-winner-presentation";
import { cn } from "@/lib/utils";

export function WinnerInsightBlocks({
  blocks,
  className,
}: {
  blocks: WinnerInsightBlock[];
  className?: string;
}) {
  return (
    <div
      className={cn("grid gap-2 sm:grid-cols-3", className)}
      data-testid="winner-insight-blocks"
    >
      {blocks.map((block) => (
        <div
          key={block.key}
          className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2.5"
          data-testid={`winner-insight-${block.key}`}
        >
          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {block.label}
          </p>
          <p className="mt-1 text-sm font-semibold leading-snug text-foreground">{block.short}</p>
          <p className="mt-1 text-xs leading-snug text-muted-foreground">{block.detail}</p>
        </div>
      ))}
    </div>
  );
}
