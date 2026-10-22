import { describe, expect, it } from "vitest";

import {
  formatViewsWithMeasurementStatus,
  viewsMeasurementLabel,
} from "./views-measurement-status";

describe("views-measurement-status", () => {
  it("labels zero views without theme failure wording", () => {
    expect(viewsMeasurementLabel("zero_in_snapshot")).toMatch(/не провал темы/);
    expect(formatViewsWithMeasurementStatus(null, "zero_in_snapshot")).toBe("0");
  });

  it("labels missing snapshot honestly", () => {
    expect(viewsMeasurementLabel("missing_snapshot")).toMatch(/Нет снимка/);
  });

  it("labels winner snapshot", () => {
    expect(viewsMeasurementLabel("from_winner_snapshot")).toMatch(/Winners/);
  });
});
