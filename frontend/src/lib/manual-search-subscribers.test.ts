import { describe, expect, it } from "vitest";

import {
  manualSearchSubscriberSkeleton,
  resolveManualSearchSubscribers,
} from "@/lib/manual-search-subscribers";
import type { EnrichedVideoModel } from "@/lib/types";

function row(subs?: number, channelId = "ch1"): EnrichedVideoModel {
  return {
    video: { video_id: "v1", channel_id: channelId, subscribers_count: subs },
    channel: { subscribers_count: subs },
    virality_coefficient: 0,
  };
}

describe("manual-search-subscribers", () => {
  it("does not treat zero as known count", () => {
    expect(resolveManualSearchSubscribers(row(0))).toBeNull();
    expect(resolveManualSearchSubscribers({ ...row(), channel: {}, video: { video_id: "v1" } })).toBeNull();
  });

  it("uses channel or video positive counts", () => {
    expect(resolveManualSearchSubscribers(row(12500))).toBe(12500);
    expect(
      resolveManualSearchSubscribers({
        video: { video_id: "v1", subscribers_count: 900 },
        channel: {},
      }),
    ).toBe(900);
  });

  it("shows skeleton only while pending and channel id exists", () => {
    expect(manualSearchSubscriberSkeleton(row(undefined), true)).toBe(true);
    expect(manualSearchSubscriberSkeleton(row(100), true)).toBe(false);
    expect(manualSearchSubscriberSkeleton(row(undefined, ""), true)).toBe(false);
    expect(manualSearchSubscriberSkeleton(row(undefined), false)).toBe(false);
  });
});
