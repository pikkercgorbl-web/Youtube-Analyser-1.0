import { describe, expect, it } from "vitest";

import {
  dailyIntelligenceThumbnailUrl,
  isValidYoutubeVideoId,
} from "./daily-intelligence-youtube";

describe("daily-intelligence-youtube", () => {
  it("accepts standard 11-char video ids", () => {
    expect(isValidYoutubeVideoId("dQw4w9WgXcQ")).toBe(true);
    expect(dailyIntelligenceThumbnailUrl("dQw4w9WgXcQ")).toBe(
      "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg",
    );
  });

  it("rejects invalid ids", () => {
    expect(isValidYoutubeVideoId("")).toBe(false);
    expect(isValidYoutubeVideoId("short")).toBe(false);
    expect(isValidYoutubeVideoId("invalid/id!")).toBe(false);
    expect(dailyIntelligenceThumbnailUrl("bad")).toBeNull();
  });
});
