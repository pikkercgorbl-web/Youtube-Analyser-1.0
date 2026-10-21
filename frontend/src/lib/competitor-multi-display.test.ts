import { describe, expect, it } from "vitest";

import {
  formatUserChannelRefLabel,
  mapCompetitorPreviewError,
  resolveChannelDisplayName,
} from "@/lib/competitor-multi-display";

describe("formatUserChannelRefLabel", () => {
  it("keeps @handle", () => {
    expect(formatUserChannelRefLabel("@MyChannel")).toBe("@MyChannel");
  });

  it("extracts handle from URL", () => {
    expect(formatUserChannelRefLabel("https://www.youtube.com/@foo")).toBe("@foo");
  });
});

describe("resolveChannelDisplayName", () => {
  it("uses API title when not a placeholder", () => {
    expect(
      resolveChannelDisplayName({
        channelTitle: "Real Name",
        channelId: "UCabcdefghijklmnop",
        inputRefs: ["@foo"],
      }),
    ).toBe("Real Name");
  });

  it("falls back to @handle when API title equals channel id", () => {
    const id = "UCabcdefghijklmnop";
    expect(
      resolveChannelDisplayName({
        channelTitle: id,
        channelId: id,
        inputRefs: ["https://youtube.com/@visible"],
      }),
    ).toBe("@visible");
  });

  it("shows loading label from user ref", () => {
    expect(
      resolveChannelDisplayName({
        channelTitle: "",
        channelId: "",
        inputRefs: ["@pending"],
        loading: true,
      }),
    ).toBe("@pending");
  });
});

describe("mapCompetitorPreviewError", () => {
  it("maps channel not found before generic 422", () => {
    const err = mapCompetitorPreviewError("Channel not found for URL: https://x", 422);
    expect(err.kind).toBe("channel_not_found");
    expect(err.title).toBe("Канал не найден");
  });

  it("maps missing ref as invalid input", () => {
    const err = mapCompetitorPreviewError("Укажите channel_ref или channel_id.", 422);
    expect(err.kind).toBe("invalid_input");
  });

  it("maps 502 as youtube unavailable", () => {
    const err = mapCompetitorPreviewError("InnerTube browse failed", 502);
    expect(err.kind).toBe("youtube_unavailable");
  });

  it("maps 503 as backend unavailable", () => {
    const err = mapCompetitorPreviewError("No API keys", 503);
    expect(err.kind).toBe("backend_unavailable");
  });
});
