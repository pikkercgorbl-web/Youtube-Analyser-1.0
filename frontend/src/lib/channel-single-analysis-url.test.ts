import { describe, expect, it } from "vitest";

import {
  buildChannelSingleAnalysisFromRefUrl,
  buildChannelSingleAnalysisUrl,
} from "@/lib/channel-single-analysis-url";

describe("channel-single-analysis-url", () => {
  it("builds channel page with focus", () => {
    const href = buildChannelSingleAnalysisUrl({
      channelId: "UCabc",
      focusVideoId: "vid123",
    });
    expect(href).toContain("/mass-analysis/channel?");
    const params = new URLSearchParams(href.split("?")[1]);
    expect(params.get("channel_id")).toBe("UCabc");
    expect(params.get("focus_video_id")).toBe("vid123");
  });

  it("builds ref entry url", () => {
    const href = buildChannelSingleAnalysisFromRefUrl("@mychannel");
    expect(href).toContain("channel_ref=%40mychannel");
  });
});
