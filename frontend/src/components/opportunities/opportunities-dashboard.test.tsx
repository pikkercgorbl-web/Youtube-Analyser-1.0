import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OpportunitiesDashboard } from "@/components/opportunities/opportunities-dashboard";
import { PatternDetailView } from "@/components/opportunities/pattern-detail";
import * as api from "@/lib/api";
import type {
  AttentionChannelListResponse,
  AttentionPatternDetailResponse,
  AttentionPatternFamilyListResponse,
  AttentionPatternListResponse,
  AttentionSummaryApiResponse,
  AttentionVideoListResponse,
  AttentionVideoWinner,
} from "@/lib/attention-types";

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...props
  }: {
    children: ReactNode;
    href: string;
    className?: string;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api", () => ({
  listSavedTopics: vi.fn().mockResolvedValue({ items: [] }),
  saveSavedTopic: vi.fn(),
  listSavedVideos: vi.fn().mockResolvedValue({ items: [] }),
  listSavedFamilies: vi.fn().mockResolvedValue({ items: [] }),
  saveSavedVideo: vi.fn(),
  saveSavedFamily: vi.fn(),
  getAttentionSummary: vi.fn(),
  getAttentionVideos: vi.fn(),
  getAttentionPatterns: vi.fn(),
  getAttentionPatternFamilies: vi.fn(),
  getAttentionChannels: vi.fn(),
  getAttentionPatternDetail: vi.fn(),
  getAttentionPatternFamilyDetail: vi.fn(),
}));

const winner = (
  overrides: Partial<AttentionVideoWinner> = {},
): AttentionVideoWinner => ({
  video_id: "vid-a",
  title: "AI cartoon tutorial",
  channel_id: "ch-a",
  channel_title: "Channel A",
  youtube_url: "https://www.youtube.com/watch?v=vid-a",
  published_at: "2026-10-01T10:00:00Z",
  age_hours: 8,
  views: 10000,
  vph: 207000,
  subscribers: null,
  breakout_rank: 1,
  breakout_eligible: true,
  channel_relative_signal: null,
  acceleration_state: "accelerating",
  delayed_outcome_state: "confirmed",
  delayed_outcome_growth: 500,
  reason_codes: [
    "breakout_high_rank",
    "accelerating_velocity",
    "confirmed_72h_growth",
  ],
  human_reasons: ["breakout_v1 rank 1 in this attention window"],
  keyword_ids: [1],
  ...overrides,
});

const summary = (): AttentionSummaryApiResponse => ({
  data_source: "snapshot",
  summary: {
    run_id: "attention_test",
    computed_at: new Date(Date.now() - 12 * 60_000).toISOString(),
    timezone_name: "UTC",
    window_hours: 24,
    window_start: "2026-09-30T12:00:00Z",
    window_end: "2026-10-01T12:00:00Z",
    source: "snapshot",
    candidate_video_count: 14553,
    winner_count: 2,
    pattern_count: 1,
    channel_momentum_count: 0,
    video_limit: 50,
    pattern_limit: 20,
    channel_limit: 20,
    notes: {},
  },
});

const videos = (items: AttentionVideoWinner[]): AttentionVideoListResponse => ({
  items,
  data_source: "snapshot",
  run_id: "attention_test",
  computed_at: "2026-10-01T12:00:00Z",
  limit: 50,
  offset: 0,
  total: items.length,
});

const patterns = (): AttentionPatternListResponse => ({
  items: [
    {
      pattern_key: "phrase:178e9c4fc2b0644e",
      kind: "title_phrase",
      label: "ai se kaise banaye",
      video_count: 57,
      channel_count: 56,
      keyword_count: 3,
      breakout_video_count: 57,
      small_channel_winner_count: 0,
      first_seen_at: "2026-09-30T00:00:00Z",
      latest_seen_at: "2026-10-01T00:00:00Z",
      videos_last_24h: 14,
      videos_previous_24h: 6,
      videos_previous_48_24h: 2,
      participating_video_ids: ["vid-a", "vid-b"],
      participating_channel_ids: ["ch-a", "ch-b"],
      participating_keyword_ids: [1],
      reason_codes: ["multi_video_evidence"],
      human_reasons: ["57 breakout-eligible videos"],
    },
  ],
  data_source: "snapshot",
  run_id: "attention_test",
  computed_at: "2026-10-01T12:00:00Z",
  limit: 20,
  offset: 0,
  total: 1,
});

const families = (): AttentionPatternFamilyListResponse => ({
  items: [
    {
      family_key: "family:phrase:abc",
      label: "ai se kaise banaye",
      family_kind: "title_phrase",
      member_pattern_keys: ["phrase:178e9c4fc2b0644e", "phrase:other"],
      member_labels: ["ai se kaise banaye", "se cartoon kaise banaye"],
      video_count: 57,
      channel_count: 56,
      keyword_count: 3,
      breakout_eligible_count: 57,
      videos_last_24h: 14,
      videos_previous_24h: 6,
      videos_previous_48_24h: 2,
      grouping_reasons: ["high_token_overlap", "shared_video_membership"],
      quality_flags: [],
      support_sources: ["title_phrase"],
      first_seen_at: "2026-09-30T00:00:00Z",
      latest_seen_at: "2026-10-01T00:00:00Z",
      participating_video_ids: ["vid-a", "vid-b"],
      participating_channel_ids: ["ch-a", "ch-b"],
      participating_keyword_ids: [1],
      opportunity_presentation_tier: "needs_review",
      grouping_basis_kind: "title_phrase_similarity",
      grouping_basis_label:
        "похожие формулировки в названиях (например: «ai se kaise banaye»)",
      tier_reason: "сходство заголовков видно по сохранённым evidence",
      feed_winner_video_ids: ["vid-a"],
      title_evidence_video_ids: ["vid-a", "vid-b"],
    },
  ],
  data_source: "snapshot",
  run_id: "attention_test",
  computed_at: "2026-10-01T12:00:00Z",
  limit: 20,
  offset: 0,
  total: 1,
});

const channelsEmpty = (): AttentionChannelListResponse => ({
  items: [],
  data_source: "snapshot",
  run_id: "attention_test",
  computed_at: "2026-10-01T12:00:00Z",
  limit: 20,
  offset: 0,
  total: 0,
});

function mockReady() {
  vi.mocked(api.getAttentionSummary).mockResolvedValue(summary());
  vi.mocked(api.getAttentionVideos).mockResolvedValue(
    videos([
      winner(),
      winner({
        video_id: "vid-b",
        title: "Second",
        youtube_url: "https://www.youtube.com/watch?v=vid-b",
        subscribers: 5000,
        breakout_rank: 2,
      }),
    ]),
  );
  vi.mocked(api.getAttentionPatternFamilies).mockResolvedValue(families());
  vi.mocked(api.getAttentionChannels).mockResolvedValue(channelsEmpty());
}

describe("Opportunities feed", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders snapshot summary, winners, patterns, and insufficient-history channels", async () => {
    mockReady();
    render(<OpportunitiesDashboard />);
    await waitFor(() =>
      expect(screen.getByTestId("snapshot-meta")).toBeInTheDocument(),
    );
    expect(screen.getByText("Возможности")).toBeInTheDocument();
    expect(screen.getByTestId("metric-winners")).toHaveTextContent("2");
    expect(screen.getByTestId("metric-patterns")).toHaveTextContent("1");
    expect(screen.getByText(/source=snapshot/)).toBeInTheDocument();
    expect(screen.getByText(/14[^\d]?553/)).toBeInTheDocument();
    expect(screen.queryByTestId("winner-card")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("winner-row").length).toBeGreaterThanOrEqual(
      2,
    );
    expect(
      screen.getAllByRole("link", { name: /AI cartoon tutorial/ })[0],
    ).toHaveAttribute("href", "https://www.youtube.com/watch?v=vid-a");
    expect(screen.queryByText("Subscribers: 0")).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: /Группы для исследования/ }),
    );
    expect(screen.getByTestId("patterns-empty")).toBeInTheDocument();
    expect(screen.getByTestId("pattern-family-card")).toHaveTextContent(
      "ai se kaise banaye",
    );
    expect(screen.getByTestId("pattern-channel-diversity")).toHaveTextContent(
      "56",
    );
    expect(screen.getByTestId("family-grouping")).toHaveTextContent("назван");
    expect(screen.getByTestId("family-feed-winners")).toHaveTextContent(
      "AI cartoon tutorial",
    );
    expect(
      screen.getAllByText(/подходят для анализа Breakout/i).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText(/breakout winner/i)).not.toBeInTheDocument();
    expect(screen.getByTestId("pattern-activity")).toHaveTextContent(
      "2 → 6 → 14",
    );
    expect(screen.getByTestId("channels-empty")).toHaveTextContent(
      "Сигналов по каналам пока нет",
    );
    expect(screen.queryByText("Растущих каналов нет")).not.toBeInTheDocument();
    expect(screen.queryByText(/магическ/i)).not.toBeInTheDocument();
    const familyCard = screen.getByTestId("pattern-family-card");
    await waitFor(() =>
      expect(
        familyCard.querySelector('[data-testid="save-family"]'),
      ).not.toHaveAttribute("disabled"),
    );

    expect(api.getAttentionSummary).toHaveBeenCalled();
    expect(vi.mocked(api.getAttentionSummary).mock.calls[0]).toEqual([]);
  });

  it("opens winners tab and focuses row when following hash from family card", async () => {
    window.history.pushState({}, "", "/opportunities");
    mockReady();
    render(<OpportunitiesDashboard />);
    await waitFor(() =>
      expect(screen.getByTestId("summary-cards")).toBeInTheDocument(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Группы для исследования/ }),
    );
    expect(screen.getByTestId("metric-winners").closest("button")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    const winnerLink = screen.getByRole("link", { name: /AI cartoon tutorial/ });
    expect(winnerLink).toHaveAttribute("href", "/opportunities#winner-vid-a");
    fireEvent.click(winnerLink);
    await waitFor(() =>
      expect(screen.getByTestId("metric-winners").closest("button")).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
    const row = document.getElementById("winner-vid-a");
    expect(row).toBeTruthy();
    expect(row?.closest("[hidden]")).toBeNull();
    window.location.hash = "";
  });

  it("does not request live recompute", async () => {
    mockReady();
    render(<OpportunitiesDashboard />);
    await waitFor(() =>
      expect(screen.getByTestId("summary-cards")).toBeInTheDocument(),
    );
    const serialized = JSON.stringify([
      vi.mocked(api.getAttentionSummary).mock.calls,
      vi.mocked(api.getAttentionVideos).mock.calls,
      vi.mocked(api.getAttentionPatternFamilies).mock.calls,
      vi.mocked(api.getAttentionChannels).mock.calls,
    ]);
    expect(serialized).not.toContain("live");
    expect(serialized).not.toContain("build_attention_engine");
  });

  it("handles unavailable snapshot", async () => {
    vi.mocked(api.getAttentionSummary).mockResolvedValue({
      summary: null,
      data_source: "unavailable",
    });
    vi.mocked(api.getAttentionVideos).mockResolvedValue(videos([]));
    vi.mocked(api.getAttentionPatternFamilies).mockResolvedValue({
      ...families(),
      items: [],
      total: 0,
    });
    vi.mocked(api.getAttentionChannels).mockResolvedValue(channelsEmpty());
    render(<OpportunitiesDashboard />);
    await waitFor(() =>
      expect(screen.getByText("Снимок Attention ещё не создан.")).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: "Состояние системы" })).toHaveAttribute(
      "href",
      "/operations",
    );
    expect(screen.getByTestId("refresh-hint")).toHaveTextContent(
      "python scripts/refresh_attention_engine.py",
    );
  });

  it("handles API error with retry", async () => {
    vi.mocked(api.getAttentionSummary).mockRejectedValue(new Error("boom"));
    vi.mocked(api.getAttentionVideos).mockRejectedValue(new Error("boom"));
    vi.mocked(api.getAttentionPatternFamilies).mockRejectedValue(
      new Error("boom"),
    );
    vi.mocked(api.getAttentionChannels).mockRejectedValue(new Error("boom"));
    render(<OpportunitiesDashboard />);
    await waitFor(() =>
      expect(screen.getByTestId("error-state")).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: "Повторить" }),
    ).toBeInTheDocument();
  });
});

describe("Pattern detail", () => {
  afterEach(() => {
    cleanup();
  });

  it("shows all member videos and technical identity", async () => {
    const detail: AttentionPatternDetailResponse = {
      data_source: "snapshot",
      run_id: "attention_test",
      computed_at: "2026-10-01T12:00:00Z",
      pattern: patterns().items[0]!,
      videos: [
        {
          video_id: "vid-a",
          title: "Member A",
          channel_id: "ch-a",
          channel_title: "Channel A",
          youtube_url: "https://www.youtube.com/watch?v=vid-a",
          published_at: "2026-10-01T10:00:00Z",
          age_hours: 4,
          views: 10,
          vph: 2,
          subscribers: null,
          in_winner_snapshot: true,
          breakout_rank: 1,
          breakout_eligible: true,
          acceleration_state: "stable",
          delayed_outcome_state: "pending",
          delayed_outcome_growth: null,
          reason_codes: [],
          human_reasons: [],
          keyword_ids: [],
        },
        {
          video_id: "vid-b",
          title: "Member B",
          channel_id: "ch-b",
          channel_title: "Channel B",
          youtube_url: "https://www.youtube.com/watch?v=vid-b",
          published_at: "2026-09-30T10:00:00Z",
          age_hours: 20,
          views: 20,
          vph: 1,
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
        },
      ],
      related_keywords: [{ keyword_id: 1, keyword: "ai cartoon" }],
      channels: [
        { channel_id: "ch-a", channel_title: "Channel A", video_count: 1 },
        { channel_id: "ch-b", channel_title: "Channel B", video_count: 1 },
      ],
    };
    vi.mocked(api.getAttentionPatternDetail).mockResolvedValue(detail);
    render(<PatternDetailView patternKey="phrase:178e9c4fc2b0644e" />);
    await waitFor(() =>
      expect(screen.getByTestId("pattern-member-list")).toBeInTheDocument(),
    );
    expect(screen.getAllByTestId("pattern-member")).toHaveLength(2);
    expect(screen.getByText("ai cartoon")).toBeInTheDocument();
    expect(screen.getAllByText("Channel B").length).toBeGreaterThan(0);
    expect(
      screen.getByText(/Источник группировки: повторяющаяся фраза/),
    ).toBeInTheDocument();
    expect(screen.getByTestId("save-pattern")).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: /Технические детали/i }),
    );
    expect(
      screen.getByText(/pattern_key: phrase:178e9c4fc2b0644e/),
    ).toBeInTheDocument();
    expect(vi.mocked(api.getAttentionPatternDetail).mock.calls[0]?.[0]).toBe(
      "phrase:178e9c4fc2b0644e",
    );
  });
});
