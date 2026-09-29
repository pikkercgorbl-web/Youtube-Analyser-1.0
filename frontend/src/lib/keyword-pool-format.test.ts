import { describe, expect, it } from "vitest";

import {
  formatNextScanPresentation,
  formatScanIntervalSeconds,
  isKeywordDue,
} from "./keyword-pool-format";
import type { TargetKeywordItem } from "./keyword-pool-types";

function row(partial: Partial<TargetKeywordItem>): TargetKeywordItem {
  return {
    id: 1,
    keyword: "test",
    created_at: "2026-01-01T00:00:00Z",
    last_checked: null,
    lifecycle_status: "active",
    scan_interval_seconds: 86400,
    next_scan_at: null,
    status_changed_at: null,
    status_reason: null,
    source_type: "seed",
    parent_keyword_id: null,
    ...partial,
  };
}

describe("keyword-pool-format", () => {
  const now = new Date("2026-09-20T12:00:00Z");

  it("marks non-archived null next_scan_at as due", () => {
    expect(isKeywordDue(row({ next_scan_at: null }), now)).toBe(true);
  });

  it('shows "Пора сканировать" when due', () => {
    const presentation = formatNextScanPresentation(
      row({ next_scan_at: "2026-09-20T10:00:00Z" }),
      now,
    );
    expect(presentation.text).toBe("Пора сканировать");
  });

  it('shows "Не сканируется" for archived', () => {
    const presentation = formatNextScanPresentation(
      row({ lifecycle_status: "archived", next_scan_at: null }),
      now,
    );
    expect(presentation.text).toBe("Не сканируется");
  });

  it("formats scan interval from seconds", () => {
    expect(formatScanIntervalSeconds(21_600)).toBe("6 ч");
    expect(formatScanIntervalSeconds(86_400)).toBe("24 ч");
    expect(formatScanIntervalSeconds(259_200)).toBe("72 ч");
  });
});
