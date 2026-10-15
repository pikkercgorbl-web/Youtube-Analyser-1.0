import { describe, expect, it } from "vitest";

import {
  attentionViewsSourceLabel,
  metricsInterpretationLabel,
  outcomeCoverageCategoryLabel,
  outcomeCoverageCategoryShortLabel,
} from "./daily-intelligence-outcome-labels";

describe("daily-intelligence-outcome-labels", () => {
  it("maps all coverage categories", () => {
    expect(outcomeCoverageCategoryLabel("MEASURED_POST_SIGNAL")).toContain("72h outcome");
    expect(outcomeCoverageCategoryLabel("MEASURED_PRE_SIGNAL")).toContain("до сигнала");
    expect(outcomeCoverageCategoryLabel("MATURED_MISSING")).toContain("закрыто");
    expect(outcomeCoverageCategoryLabel("INVALID_TIMELINE")).toContain("последовательность");
    expect(outcomeCoverageCategoryLabel("INSUFFICIENT_EVIDENCE")).toContain("Недостаточно");
  });

  it("maps NOT_MATURED phases", () => {
    expect(outcomeCoverageCategoryLabel("NOT_MATURED", "not_yet_open")).toBe(
      "Окно измерения ещё не открыто",
    );
    expect(outcomeCoverageCategoryLabel("NOT_MATURED", "open_awaiting_measurement")).toBe(
      "Ожидается измерение",
    );
  });

  it("uses short labels in table badges", () => {
    expect(outcomeCoverageCategoryShortLabel("MEASURED_POST_SIGNAL")).toBe("Post-signal");
    expect(outcomeCoverageCategoryShortLabel("MATURED_MISSING")).toBe("Нет снимка");
  });

  it("labels provenance and interpretation", () => {
    expect(attentionViewsSourceLabel("frozen_payload_unknown_source")).toContain("доказан");
    expect(metricsInterpretationLabel("verified_post_signal_growth_unavailable")).toContain(
      "недоступен",
    );
    expect(metricsInterpretationLabel("pre_signal_outcome_only")).toContain("post-signal");
  });
});
