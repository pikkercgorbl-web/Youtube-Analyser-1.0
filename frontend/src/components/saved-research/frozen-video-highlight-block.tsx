"use client";

import type { FrozenVideoHighlightView } from "@/lib/opportunity-winner-presentation";

export function FrozenVideoHighlightBlock({ view }: { view: FrozenVideoHighlightView }) {
  if (view.kind === "none") {
    return null;
  }
  if (view.kind === "manual") {
    return (
      <div
        className="mt-3 rounded-xl border border-border/60 bg-muted/20 p-3 text-sm"
        data-testid="frozen-video-highlight"
      >
        <p className="font-medium">Чем выделялось видео</p>
        <p className="mt-1 text-muted-foreground">Сохранено из ручного поиска</p>
        <p className="mt-2 text-xs text-muted-foreground">На момент сохранения</p>
      </div>
    );
  }
  return (
    <div
      className="mt-3 rounded-xl border border-border/60 bg-muted/20 p-3 text-sm"
      data-testid="frozen-video-highlight"
    >
      <p className="font-medium">Чем выделялось видео</p>
      <p className="mt-1 text-base font-semibold text-foreground">{view.headline}</p>
      {view.detail ? (
        <p className="mt-1 text-sm text-muted-foreground leading-snug">{view.detail}</p>
      ) : null}
      <p className="mt-2 text-xs text-muted-foreground">На момент сохранения</p>
    </div>
  );
}
