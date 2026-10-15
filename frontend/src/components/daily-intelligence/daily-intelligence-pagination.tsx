"use client";

import { Button } from "@/components/ui/button";

export function DailyIntelligencePagination({
  total,
  offset,
  limit,
  onPageChange,
  disabled,
}: {
  total: number;
  offset: number;
  limit: number;
  onPageChange: (nextOffset: number) => void;
  disabled?: boolean;
}) {
  if (total <= limit) {
    return (
      <p className="text-xs text-muted-foreground tabular-nums">
        Показано {total} из {total}
      </p>
    );
  }
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-xs text-muted-foreground tabular-nums">
        {offset + 1}–{Math.min(offset + limit, total)} из {total}
      </p>
      <div className="flex gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled || offset <= 0}
          onClick={() => onPageChange(Math.max(0, offset - limit))}
        >
          Назад
        </Button>
        <span className="text-xs text-muted-foreground self-center tabular-nums">
          {page} / {pages}
        </span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled || offset + limit >= total}
          onClick={() => onPageChange(offset + limit)}
        >
          Вперёд
        </Button>
      </div>
    </div>
  );
}
