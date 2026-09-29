import {
  isKeywordDue,
  isScheduledWithin24h,
  matchesUnscheduledOrArchived,
} from "./keyword-pool-format";
import type {
  PoolDueFilter,
  PoolLifecycleFilter,
  PoolSortKey,
  PoolSourceFilter,
  TargetKeywordItem,
} from "./keyword-pool-types";

const LIFECYCLE_ORDER: Record<string, number> = {
  probation: 0,
  active: 1,
  weak: 2,
  archived: 3,
};

export function filterPoolRows(
  rows: TargetKeywordItem[],
  {
    search,
    lifecycle,
    source,
    due,
    now,
  }: {
    search: string;
    lifecycle: PoolLifecycleFilter;
    source: PoolSourceFilter;
    due: PoolDueFilter;
    now: Date;
  },
): TargetKeywordItem[] {
  const q = search.trim().toLowerCase();
  return rows.filter((row) => {
    if (q && !row.keyword.toLowerCase().includes(q)) {
      return false;
    }
    if (lifecycle !== "all" && row.lifecycle_status !== lifecycle) {
      return false;
    }
    if (source !== "all" && row.source_type !== source) {
      return false;
    }
    if (due === "due" && !isKeywordDue(row, now)) {
      return false;
    }
    if (due === "next_24h" && !isScheduledWithin24h(row, now)) {
      return false;
    }
    if (due === "unscheduled_or_archived" && !matchesUnscheduledOrArchived(row)) {
      return false;
    }
    return true;
  });
}

function nextScanSortKey(row: TargetKeywordItem, now: Date): number {
  if (row.lifecycle_status === "archived") {
    return Number.MAX_SAFE_INTEGER;
  }
  if (isKeywordDue(row, now)) {
    return 0;
  }
  if (!row.next_scan_at) {
    return 0;
  }
  const at = new Date(row.next_scan_at).getTime();
  return Number.isNaN(at) ? 0 : at;
}

export function sortPoolRows(
  rows: TargetKeywordItem[],
  sortKey: PoolSortKey,
  now: Date,
): TargetKeywordItem[] {
  const copy = [...rows];
  copy.sort((a, b) => {
    switch (sortKey) {
      case "keyword":
        return a.keyword.localeCompare(b.keyword, "ru");
      case "lifecycle": {
        const ao = LIFECYCLE_ORDER[a.lifecycle_status] ?? 50;
        const bo = LIFECYCLE_ORDER[b.lifecycle_status] ?? 50;
        return ao - bo || a.keyword.localeCompare(b.keyword, "ru");
      }
      case "last_checked": {
        const at = a.last_checked ? new Date(a.last_checked).getTime() : 0;
        const bt = b.last_checked ? new Date(b.last_checked).getTime() : 0;
        return bt - at;
      }
      case "next_scan_at":
      default: {
        const diff = nextScanSortKey(a, now) - nextScanSortKey(b, now);
        return diff || a.keyword.localeCompare(b.keyword, "ru");
      }
    }
  });
  return copy;
}
