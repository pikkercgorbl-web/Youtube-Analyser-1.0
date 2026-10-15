"use client";

import { formatChannelBaselineExplanation } from "@/lib/channel-baseline-copy";
import type { ChannelRelativeLike } from "@/lib/channel-baseline-copy";

export function ChannelBaselinePanel({
  rel,
  className,
}: {
  rel: ChannelRelativeLike;
  className?: string;
}) {
  const copy = formatChannelBaselineExplanation(rel);
  return (
    <div
      className={className}
      data-testid={copy.dataTestId}
    >
      <p className="text-sm font-medium text-foreground">{copy.headline}</p>
      <p className="mt-1 text-sm text-muted-foreground">{copy.body}</p>
      {copy.limitation ? (
        <p className="mt-2 text-xs text-muted-foreground">{copy.limitation}</p>
      ) : null}
    </div>
  );
}
