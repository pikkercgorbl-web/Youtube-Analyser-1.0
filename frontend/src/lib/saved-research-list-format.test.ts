import { describe, expect, it } from "vitest";

import { formatFamilyCountLine, formatMeasurementSource } from "./saved-research-list-format";
import type { SavedFamilyListItem } from "./saved-research-types";

function family(partial: Partial<SavedFamilyListItem>): SavedFamilyListItem {
  return {
    id: 1,
    family_key: "k",
    label: "L",
    status: "WATCHING",
    notes: "",
    tags: [],
    saved_at: "",
    updated_at: "",
    archived_at: null,
    latest_observed_at: null,
    family_present: null,
    frozen_video_count: null,
    current_video_count: null,
    frozen_channel_count: null,
    current_channel_count: null,
    latest_analyst_verdict: null,
    latest_analyst_verdict_at: null,
    ...partial,
  };
}

describe("saved-research-list-format", () => {
  it("formats measurement source labels", () => {
    expect(formatMeasurementSource(null)).toBe("—");
    expect(formatMeasurementSource("manual_saved_video_refresh")).toContain("ручное");
  });

  it("shows bounded snapshot absence for families", () => {
    const line = formatFamilyCountLine(
      family({
        family_present: false,
        frozen_video_count: 16,
        current_video_count: 16,
      }),
    );
    expect(line).toContain("нет в bounded snapshot");
  });

  it("warns when video count unchanged", () => {
    const line = formatFamilyCountLine(
      family({
        family_present: true,
        frozen_video_count: 16,
        current_video_count: 16,
        frozen_channel_count: 3,
        current_channel_count: 3,
      }),
    );
    expect(line).toContain("без изменения числа");
    expect(line).toContain("каналы");
  });

  it("shows delta when counts differ", () => {
    const line = formatFamilyCountLine(
      family({
        frozen_video_count: 10,
        current_video_count: 14,
      }),
    );
    expect(line).toBe("видео: 10 → 14");
  });
});
