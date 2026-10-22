import { render, screen } from "@testing-library/react";

import { describe, expect, it, vi } from "vitest";



import type { AttentionPatternFamilyDetailResponse } from "@/lib/attention-types";



import { PatternFamilyDetailView } from "./pattern-family-detail";



vi.mock("@/lib/api", async (importOriginal) => {

  const actual = await importOriginal<typeof import("@/lib/api")>();

  return {

    ...actual,

    getAttentionPatternFamilyDetail: vi.fn(),

    listSavedFamilies: vi.fn().mockResolvedValue({ items: [], total: 0 }),

    listSavedVideos: vi.fn().mockResolvedValue({ items: [], total: 0 }),

    saveSavedVideo: vi.fn(),

  };

});



vi.mock("next/link", () => ({

  default: ({ children, href }: { children: React.ReactNode; href: string }) => (

    <a href={href}>{children}</a>

  ),

}));



const baseFamily = {

  family_key: "fam:kw:1",

  label: "minecraft challenge videos",

  family_kind: "keyword_provenance",

  member_pattern_keys: ["kw:1"],

  member_labels: ["query group"],

  video_count: 2,

  channel_count: 2,

  keyword_count: 1,

  breakout_eligible_count: 0,

  videos_last_24h: 0,

  videos_previous_24h: 0,

  videos_previous_48_24h: 0,

  grouping_reasons: ["shared_video_membership"],

  quality_flags: ["keyword_only"],

  support_sources: ["keyword"],

  first_seen_at: null,

  latest_seen_at: null,

  participating_video_ids: ["v1", "v2"],

  participating_channel_ids: ["c1", "c2"],

  participating_keyword_ids: [1],

  opportunity_presentation_tier: "search_collection" as const,

  grouping_basis_kind: "single_search_query",

  grouping_basis_label: "Один поисковый запрос",

  tier_reason: "Подборка по keyword.",

  feed_winner_video_ids: ["v1"],

  title_evidence_video_ids: [],

};



const detail: AttentionPatternFamilyDetailResponse = {

  family: baseFamily,

  data_source: "snapshot",

  run_id: "run1",

  computed_at: "2026-10-13T00:00:00Z",

  related_keywords: [{ keyword_id: 1, keyword: "ai tutorial" }],

  channels: [],

  videos: [

    {

      video_id: "v1",

      title: "Winner title",

      channel_id: "c1",

      channel_title: "Ch1",

      youtube_url: "https://www.youtube.com/watch?v=v1",

      published_at: null,

      age_hours: 10,

      views: 1000,

      vph: 100,

      subscribers: null,

      in_winner_snapshot: true,

      breakout_rank: 1,

      breakout_eligible: true,

      acceleration_state: "accelerating",

      delayed_outcome_state: "pending",

      delayed_outcome_growth: null,

      reason_codes: [],

      human_reasons: [],

      keyword_ids: [1],

      views_measurement_status: "from_winner_snapshot",

      discovery_keywords: [{ keyword_id: 1, keyword: "ai tutorial" }],

    },

    {

      video_id: "v2",

      title: "Raw member",

      channel_id: "c2",

      channel_title: "Ch2",

      youtube_url: "https://www.youtube.com/watch?v=v2",

      published_at: null,

      age_hours: null,

      views: null,

      vph: null,

      subscribers: null,

      in_winner_snapshot: false,

      breakout_rank: null,

      breakout_eligible: null,

      acceleration_state: null,

      delayed_outcome_state: null,

      delayed_outcome_growth: null,

      reason_codes: [],

      human_reasons: [],

      keyword_ids: [],

      views_measurement_status: "missing_snapshot",

      discovery_keywords: [],

    },

  ],

};



describe("PatternFamilyDetailView", () => {

  it("shows search headline, winner facts, cards and diagnostic block", async () => {

    const { getAttentionPatternFamilyDetail } = await import("@/lib/api");

    vi.mocked(getAttentionPatternFamilyDetail).mockResolvedValue(detail);



    render(<PatternFamilyDetailView familyKey="fam:kw:1" />);



    expect(await screen.findByTestId("family-detail-header")).toBeInTheDocument();

    expect(screen.getByText(/Подборка по поисковому запросу «ai tutorial»/i)).toBeInTheDocument();

    expect(screen.getByText(/не означает, что у них один формат/i)).toBeInTheDocument();

    expect(screen.getByTestId("family-detail-feed-winners")).toHaveTextContent("1");

    expect(screen.queryByText(/Выборка Breakout/i)).not.toBeInTheDocument();



    const cards = screen.getAllByTestId("family-member-card");

    expect(cards).toHaveLength(2);

    expect(cards[0]).toHaveAttribute("data-in-winner-snapshot", "true");

    expect(screen.getByRole("link", { name: "Детали видео" })).toHaveAttribute(

      "href",

      "/opportunities/videos/v1",

    );

    expect(screen.getByText(/Просмотры из снимка Winners/i)).toBeInTheDocument();

    expect(screen.getAllByText("Нет измерения").length).toBeGreaterThan(0);

    expect(screen.getByText(/Как сформирована подборка/i)).toBeInTheDocument();

  });

});


