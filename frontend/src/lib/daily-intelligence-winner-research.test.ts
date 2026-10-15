import { describe, expect, it } from "vitest";

import { formatWinnerMetrics } from "@/lib/daily-intelligence-evidence-format";

import {
  buildAttentionSummaryParagraph,
  outcomeComparisonLimitationNote,
  outcomeResearchCopy,
} from "./daily-intelligence-winner-research";
import type { DailyIntelligenceWinnerOutcomeFollowUp } from "./daily-intelligence-outcome-types";

describe("daily-intelligence-winner-research", () => {
  it("builds deterministic attention summary from evidence", () => {
    const metrics = formatWinnerMetrics({
      views: 12000,
      vph: 800,
      age_hours: 6,
      breakout_rank: 2,
      human_reasons: ["Высокий темп роста"],
    });
    const text = buildAttentionSummaryParagraph(metrics, metrics.humanReasons);
    expect(text).toContain("Высокий темп роста");
    expect(text).toContain("просмотров в час");
  });

  it("maps outcome categories to human copy", () => {
    expect(outcomeResearchCopy("MEASURED_POST_SIGNAL").headline).toContain("Контрольное");
    expect(outcomeResearchCopy("NOT_MATURED", "not_yet_open").tone).toBe("pending");
    expect(outcomeResearchCopy("INSUFFICIENT_EVIDENCE").tone).toBe("muted");
  });

  it("shows limitation note when baseline not verified", () => {
    const followUp = {
      coverage_category: "MEASURED_POST_SIGNAL",
      attention_views_provenance: { baseline_provenance_verified: false },
      comparison_metrics: { delta_views_descriptive: 100 },
    } as DailyIntelligenceWinnerOutcomeFollowUp;
    expect(outcomeComparisonLimitationNote(followUp)).toContain("не подтверждено");
  });
});
