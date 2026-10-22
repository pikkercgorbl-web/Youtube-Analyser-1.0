import { describe, expect, it } from "vitest";

import {
  isCurrentGeneration,
  shouldRunFocusCompare,
} from "@/lib/channel-single-analysis-loading";

describe("channel-single-analysis-loading", () => {
  it("clears loading only for the active enrich generation (regression)", () => {
    const enrichGeneration = 2;
    expect(isCurrentGeneration(enrichGeneration, 2)).toBe(true);
    // Bug: comparing enrich generation to shelf generation left loading stuck.
    expect(isCurrentGeneration(enrichGeneration, 1)).toBe(false);
  });

  it("skips compare on first load when focus unchanged after enrich", () => {
    expect(shouldRunFocusCompare("vidA", "vidA", true)).toBe(false);
  });

  it("runs compare when focus changes after enrich ready", () => {
    expect(shouldRunFocusCompare("vidA", "vidB", true)).toBe(true);
  });

  it("does not compare before enrich ready", () => {
    expect(shouldRunFocusCompare("", "vidB", false)).toBe(false);
  });
});
