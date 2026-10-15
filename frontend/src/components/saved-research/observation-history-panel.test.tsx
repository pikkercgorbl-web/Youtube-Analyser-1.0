import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ObservationHistoryPanel } from "./observation-history-panel";
import { DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND } from "@/lib/saved-research-labels";
import type { SavedFamilyObservation } from "@/lib/saved-research-types";

const anchorRow: SavedFamilyObservation = {
  id: 1,
  attention_run_id: "attention_test",
  observed_at: "2026-10-10T14:08:09+00:00",
  family_present: false,
  label: "Acc Fam",
  video_count: null,
  channel_count: null,
  keyword_count: null,
  payload: {
    observation_kind: DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND,
    counts: { video_count: 2, channel_count: 2 },
    family: { label: "Acc Fam", video_count: 2, channel_count: 2 },
  },
  absence_message: null,
};

describe("ObservationHistoryPanel family anchor", () => {
  it("does not show live absence for historical anchor", () => {
    render(
      <ObservationHistoryPanel
        kind="family"
        items={[anchorRow]}
        total={1}
        loading={false}
        hasMore={false}
      />,
    );
    expect(screen.getByText("Сохранено из исторического отчёта")).toBeInTheDocument();
    expect(screen.queryByText(/не в текущей выборке Attention/i)).not.toBeInTheDocument();
    expect(screen.getByText(/видео 2/)).toBeInTheDocument();
  });
});
