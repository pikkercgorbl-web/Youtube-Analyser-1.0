import { describe, expect, it } from "vitest";

import {
  CHANNEL_SINGLE_COMPARE_BUTTON_LABEL,
  CHANNEL_SINGLE_COMPARE_HINT,
  CHANNEL_SINGLE_COMPARE_METHOD_NOTE,
} from "./channel-single-analysis-copy";

describe("channel-single-analysis-copy", () => {
  it("matches age-peer methodology keywords", () => {
    expect(CHANNEL_SINGLE_COMPARE_HINT).toMatch(/обычными видео/);
    expect(CHANNEL_SINGLE_COMPARE_BUTTON_LABEL).toBe("Сравнить этот ролик");
    expect(CHANNEL_SINGLE_COMPARE_METHOD_NOTE).toMatch(/75%/);
    expect(CHANNEL_SINGLE_COMPARE_METHOD_NOTE).toMatch(/125%/);
    expect(CHANNEL_SINGLE_COMPARE_METHOD_NOTE).toMatch(/5/);
    expect(CHANNEL_SINGLE_COMPARE_METHOD_NOTE).toMatch(/48/);
  });
});
