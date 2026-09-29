"use client";

import { textRoles } from "@/lib/design-system/typography";
import { formatDateTimeLocal } from "@/lib/monitoring-format";
import { cn } from "@/lib/utils";

/** Relative time from server reference (generated_at), not client clock when provided. */
export function formatRelativeFromReference(
  iso: string | null | undefined,
  referenceIso: string | null | undefined,
): { relative: string; title: string; never: boolean } {
  const title = formatDateTimeLocal(iso);
  if (!iso) {
    return { relative: "никогда", title: "—", never: true };
  }
  if (!referenceIso) {
    return { relative: formatDateTimeLocal(iso), title, never: false };
  }
  const at = new Date(iso).getTime();
  const ref = new Date(referenceIso).getTime();
  if (Number.isNaN(at) || Number.isNaN(ref)) {
    return { relative: "—", title, never: false };
  }
  const diffMs = ref - at;
  if (diffMs < 0) {
    return { relative: formatDateTimeLocal(iso), title, never: false };
  }
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) {
    return { relative: "только что", title, never: false };
  }
  if (minutes < 60) {
    return { relative: `${minutes} мин назад`, title, never: false };
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 48) {
    return { relative: `${hours} ч назад`, title, never: false };
  }
  const days = Math.floor(hours / 24);
  return { relative: `${days} д назад`, title, never: false };
}

export function FreshnessTime({
  iso,
  referenceIso,
  className,
  staleAfterDays,
}: {
  iso: string | null | undefined;
  referenceIso?: string | null;
  className?: string;
  staleAfterDays?: number;
}) {
  const { relative, title, never } = formatRelativeFromReference(iso, referenceIso ?? null);
  let stale = false;
  if (staleAfterDays != null && iso && referenceIso) {
    const diffDays =
      (new Date(referenceIso).getTime() - new Date(iso).getTime()) / (86400 * 1000);
    stale = diffDays >= staleAfterDays;
  }

  return (
    <time
      dateTime={iso ?? undefined}
      title={title}
      className={cn(
        textRoles.tableCell,
        never && "text-muted-foreground",
        stale && "text-status-warn",
        className,
      )}
    >
      {relative}
    </time>
  );
}
