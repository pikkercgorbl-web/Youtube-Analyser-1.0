import { describe, expect, it } from "vitest";

import { APP_TIMEZONE } from "@/lib/app-timezone";
import {
  calendarDayEndUtcIso,
  calendarDayStartUtcIso,
  formatValidationPeriodLabel,
  parseValidationPeriodSearchParams,
  utcInstantWithinValidationPeriod,
  validationPeriodHref,
  validationPeriodToApiParams,
} from "@/lib/validation-period";

const ALMATY = "Asia/Almaty";
const SAMPLE_DAY = "2026-03-15";

describe("APP_TIMEZONE default", () => {
  it("defaults to Asia/Almaty when env unset", () => {
    expect(APP_TIMEZONE).toBe("Asia/Almaty");
  });
});

describe("parseValidationPeriodSearchParams", () => {
  it("accepts valid from/to", () => {
    const p = parseValidationPeriodSearchParams(
      new URLSearchParams("from=2026-01-01&to=2026-01-31"),
    );
    expect(p.urlCorrected).toBe(false);
    expect(p.dates).toEqual({ from: "2026-01-01", to: "2026-01-31" });
  });

  it("rejects inverted range without API call semantics", () => {
    const p = parseValidationPeriodSearchParams(
      new URLSearchParams("from=2026-02-01&to=2026-01-01"),
    );
    expect(p.urlCorrected).toBe(true);
    expect(p.dates).toEqual({ from: "", to: "" });
    expect(p.urlIssue).toMatch(/позже/i);
  });

  it("rejects malformed date", () => {
    const p = parseValidationPeriodSearchParams(new URLSearchParams("from=2026-13-40"));
    expect(p.urlCorrected).toBe(true);
    expect(p.dates.from).toBe("");
  });
});

describe("validationPeriodToApiParams", () => {
  it("includes full end calendar day in configured timezone", () => {
    const params = validationPeriodToApiParams({
      from: "2026-01-15",
      to: "2026-01-15",
    });
    expect(params.period_start).toBeTruthy();
    expect(params.period_end).toBeTruthy();
    const end = new Date(params.period_end!);
    const start = new Date(params.period_start!);
    expect(end.getTime()).toBeGreaterThan(start.getTime());
    expect(end.getTime() - start.getTime()).toBeGreaterThan(23 * 60 * 60 * 1000);
  });
});

describe("Asia/Almaty single-day contract", () => {
  it("exposes exact UTC bounds for one calendar day", () => {
    expect(calendarDayStartUtcIso(SAMPLE_DAY, ALMATY)).toBe("2026-03-14T19:00:00.000Z");
    expect(calendarDayEndUtcIso(SAMPLE_DAY, ALMATY)).toBe("2026-03-15T18:59:59.999Z");
  });

  it("URL, label and API bounds refer to the same calendar dates", () => {
    const dates = { from: SAMPLE_DAY, to: SAMPLE_DAY };
    expect(validationPeriodHref(dates)).toBe(`/validation?from=${SAMPLE_DAY}&to=${SAMPLE_DAY}`);
    expect(formatValidationPeriodLabel(dates)).toBe("15.03.2026 — 15.03.2026");
    const api = validationPeriodToApiParams(dates);
    expect(api.period_start).toBe("2026-03-14T19:00:00.000Z");
    expect(api.period_end).toBe("2026-03-15T18:59:59.999Z");
  });

  it("includes records at start and end of calendar day boundaries", () => {
    const dates = { from: SAMPLE_DAY, to: SAMPLE_DAY };
    expect(utcInstantWithinValidationPeriod("2026-03-14T19:00:00.000Z", dates, ALMATY)).toBe(true);
    expect(utcInstantWithinValidationPeriod("2026-03-15T18:59:59.999Z", dates, ALMATY)).toBe(true);
    expect(utcInstantWithinValidationPeriod("2026-03-14T18:59:59.999Z", dates, ALMATY)).toBe(false);
    expect(utcInstantWithinValidationPeriod("2026-03-15T19:00:00.000Z", dates, ALMATY)).toBe(false);
  });
});

describe("formatValidationPeriodLabel", () => {
  it("shows dates without time", () => {
    expect(
      formatValidationPeriodLabel({ from: "2026-03-01", to: "2026-03-07" }),
    ).toBe("01.03.2026 — 07.03.2026");
  });
});
