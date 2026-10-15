import { describe, expect, it } from "vitest";

import type { AttentionPatternFamily } from "@/lib/attention-types";
import {
  familySectionBadge,
  isRepeatingIdeaFamily,
  isSearchCollectionFamily,
  parseWinnerVideoIdFromHash,
  winnerFeedHref,
} from "@/lib/opportunity-family-presentation";

const baseFamily = (
  overrides: Partial<AttentionPatternFamily> = {},
): AttentionPatternFamily => ({
  family_key: "family:kw:1",
  label: "sample",
  family_kind: "keyword_provenance",
  member_pattern_keys: ["keyword:1"],
  member_labels: ["sample"],
  video_count: 2,
  channel_count: 2,
  keyword_count: 1,
  breakout_eligible_count: 0,
  videos_last_24h: 0,
  videos_previous_24h: 0,
  videos_previous_48_24h: 0,
  grouping_reasons: [],
  quality_flags: [],
  support_sources: ["keyword"],
  first_seen_at: null,
  latest_seen_at: null,
  participating_video_ids: ["v1", "v2"],
  participating_channel_ids: ["c1", "c2"],
  participating_keyword_ids: [1],
  opportunity_presentation_tier: "search_collection",
  grouping_basis_kind: "single_search_query",
  grouping_basis_label: "найдены по одному запросу",
  tier_reason: "",
  feed_winner_video_ids: [],
  title_evidence_video_ids: [],
  ...overrides,
});

describe("opportunity family presentation helpers", () => {
  it("classifies search collections and winner anchors", () => {
    const family = baseFamily();
    expect(isSearchCollectionFamily(family)).toBe(true);
    expect(isRepeatingIdeaFamily(family)).toBe(false);
    expect(familySectionBadge(family)).toBe("Подборка поиска");
    expect(winnerFeedHref("vid-a")).toBe("/opportunities#winner-vid-a");
    expect(parseWinnerVideoIdFromHash("#winner-vid-a")).toBe("vid-a");
  });

  it("preserves family_key in unrelated fields", () => {
    const family = baseFamily({ family_key: "family:phrase:abc123" });
    expect(family.family_key).toBe("family:phrase:abc123");
  });
});
