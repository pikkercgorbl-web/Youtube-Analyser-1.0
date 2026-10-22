import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type {
  AttentionChannelMomentum,
  AttentionChannelRepresentativeVideo,
} from "@/lib/attention-types";

import { RisingChannelsSection } from "./rising-channels";

afterEach(cleanup);

const channel = (overrides: Partial<AttentionChannelMomentum>): AttentionChannelMomentum => ({
  channel_id: "UC1",
  channel_title: "Тайны Древних",
  subscriber_count_latest: 25_700,
  observed_video_count: 10,
  recent_video_count: 4,
  previous_video_count: 6,
  breakout_video_count: 0,
  confirmed_72h_count: 0,
  recent_median_vph: 50,
  previous_median_vph: 82,
  recent_median_vph_vs_previous: 0.61,
  subscriber_growth_absolute: null,
  subscriber_growth_pct: null,
  subscriber_growth_available: false,
  first_observed_at: null,
  latest_observed_at: null,
  representative_video_ids: ["vid-a", "vid-b"],
  reason_codes: ["repeated_age_aligned_improvement"],
  human_reasons: ["2 recent videos at ~24h (±6.0h) each ≥ 1.5× previous median 82.0 VPH"],
  recent_window_days: 7,
  previous_window_days: 7,
  recent_measurable_count: 2,
  previous_measurable_count: 2,
  recent_improvement_count: 2,
  improvement_ratio_threshold: 1.5,
  previous_baseline_zero: false,
  incompleteness_notes: ["1 recent eligible without snapshot"],
});

const repVideos: AttentionChannelRepresentativeVideo[] = [
  {
    video_id: "vid-a",
    title: "Example video A",
    youtube_url: "https://www.youtube.com/watch?v=vid-a",
    horizon_vph: 120,
    measured_at: "2026-10-19T12:00:00Z",
    actual_age_hours: 24,
    target_horizon_hours: 24,
    vs_previous_median_ratio: 1.8,
    meets_improvement_threshold: true,
    unavailable_reason: null,
  },
];

describe("RisingChannelsSection", () => {
  it("shows outlier headline for 0.61x median with strong videos", () => {
    render(
      <RisingChannelsSection
        channels={[channel({ representative_videos: repVideos })]}
      />,
    );
    expect(screen.getByText("Отдельные сильные ролики")).toBeInTheDocument();
    expect(screen.queryByText("Есть сигнал роста")).not.toBeInTheDocument();
    expect(screen.getByText(/0\.61×/)).toBeInTheDocument();
    expect(screen.queryByText(/подходят для анализа Breakout/i)).not.toBeInTheDocument();
  });

  it("shows honest message when horizon VPH is missing", () => {
    render(
      <RisingChannelsSection
        channels={[
          channel({
            representative_videos: [
              {
                video_id: "vid-a",
                title: "No snap",
                youtube_url: "https://www.youtube.com/watch?v=vid-a",
                horizon_vph: null,
                measured_at: null,
                actual_age_hours: null,
                target_horizon_hours: 24,
                vs_previous_median_ratio: null,
                meets_improvement_threshold: null,
                unavailable_reason: "no_snapshot_near_horizon",
              },
            ],
          }),
        ]}
      />,
    );
    expect(screen.getByTestId("channel-evidence-unavailable")).toHaveTextContent(
      /age-aligned VPH/i,
    );
  });

  it("hides raw diagnostics until expanded", () => {
    render(
      <RisingChannelsSection
        channels={[channel({ representative_videos: repVideos })]}
      />,
    );
    expect(screen.queryByTestId("channel-calc-details")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("channel-calc-toggle"));
    expect(screen.getByTestId("channel-calc-details")).toBeInTheDocument();
  });

  it("renders empty state", () => {
    render(<RisingChannelsSection channels={[]} />);
    expect(screen.getByTestId("channels-empty")).toBeInTheDocument();
  });

  it("shows category summary for non-empty list", () => {
    render(
      <RisingChannelsSection
        channels={[
          channel({ channel_id: "UC-a", recent_median_vph_vs_previous: 0.61 }),
          channel({
            channel_id: "UC-b",
            channel_title: "Higher median",
            recent_median_vph_vs_previous: 1.35,
            recent_measurable_count: 5,
            previous_measurable_count: 2,
          }),
        ]}
      />,
    );
    expect(screen.getByTestId("channels-category-summary")).toHaveTextContent(
      "2 каналов в снимке",
    );
    expect(screen.getAllByTestId("channel-card")).toHaveLength(2);
  });
});
