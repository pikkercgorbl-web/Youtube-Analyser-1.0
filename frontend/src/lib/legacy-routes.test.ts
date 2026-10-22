import { describe, expect, it } from "vitest";

import { LEGACY_ROUTE_REDIRECTS } from "./legacy-routes";
import { parseOpportunitiesSectionFromHash } from "./opportunities-section-hash";

describe("LEGACY_ROUTE_REDIRECTS", () => {
  it("maps explosive and leaders radar to opportunities channels", () => {
    expect(LEGACY_ROUTE_REDIRECTS["explosive-channels"]).toBe("/opportunities#section=channels");
    expect(LEGACY_ROUTE_REDIRECTS.leaders).toBe("/opportunities#section=channels");
  });

  it("maps anomalies to manual search home", () => {
    expect(LEGACY_ROUTE_REDIRECTS.anomalies).toBe("/");
  });
});

describe("parseOpportunitiesSectionFromHash", () => {
  it("parses section=channels from legacy redirects", () => {
    expect(parseOpportunitiesSectionFromHash("#section=channels")).toBe("channels");
    expect(parseOpportunitiesSectionFromHash("#channels")).toBe("channels");
  });
});
