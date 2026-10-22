/**
 * Calendar period for «Итоги исследований» (VAL-05).
 * URL: ?from=YYYY-MM-DD&to=YYYY-MM-DD (календарные даты в APP_TIMEZONE)
 * API: inclusive calendar days in APP_TIMEZONE → UTC ISO bounds.
 */

import { APP_TIMEZONE } from "@/lib/app-timezone";

export { APP_TIMEZONE, VALIDATION_PERIOD_TIMEZONE } from "@/lib/app-timezone";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export type ValidationPeriodDates = {
  from: string;
  to: string;
};

export type ParsedValidationPeriod = {
  dates: ValidationPeriodDates;
  /** True when URL params were invalid and replaced with safe defaults. */
  urlCorrected: boolean;
  urlIssue: string | null;
};

export function isValidCalendarDate(isoDate: string): boolean {
  if (!DATE_RE.test(isoDate)) return false;
  const [y, m, d] = isoDate.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return (
    dt.getUTCFullYear() === y &&
    dt.getUTCMonth() === m - 1 &&
    dt.getUTCDate() === d
  );
}

export function defaultValidationPeriod(): ValidationPeriodDates {
  return { from: "", to: "" };
}

export function parseValidationPeriodSearchParams(
  params: URLSearchParams,
): ParsedValidationPeriod {
  const rawFrom = params.get("from")?.trim() ?? "";
  const rawTo = params.get("to")?.trim() ?? "";

  if (!rawFrom && !rawTo) {
    return {
      dates: defaultValidationPeriod(),
      urlCorrected: false,
      urlIssue: null,
    };
  }

  const issues: string[] = [];
  let from = rawFrom;
  let to = rawTo;

  if (from && !isValidCalendarDate(from)) {
    issues.push("некорректная дата «с»");
    from = "";
  }
  if (to && !isValidCalendarDate(to)) {
    issues.push("некорректная дата «по»");
    to = "";
  }
  if (from && to && from > to) {
    issues.push("дата «с» позже даты «по»");
    return {
      dates: defaultValidationPeriod(),
      urlCorrected: true,
      urlIssue: issues.join("; "),
    };
  }

  if (issues.length) {
    return {
      dates: defaultValidationPeriod(),
      urlCorrected: true,
      urlIssue: issues.join("; "),
    };
  }

  return {
    dates: { from, to },
    urlCorrected: issues.length > 0,
    urlIssue: issues.length ? issues.join("; ") : null,
  };
}

export function validationPeriodQueryString(dates: ValidationPeriodDates): string {
  const params = new URLSearchParams();
  if (dates.from) params.set("from", dates.from);
  if (dates.to) params.set("to", dates.to);
  const q = params.toString();
  return q ? `?${q}` : "";
}

export function validationPeriodHref(dates: ValidationPeriodDates): string {
  return `/validation${validationPeriodQueryString(dates)}`;
}

function timeZoneOffsetMs(timeZone: string, instant: Date): number {
  const dtf = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  const parts = dtf.formatToParts(instant);
  const filled: Record<string, string> = {};
  for (const part of parts) {
    if (part.type !== "literal") filled[part.type] = part.value;
  }
  const asUtc = Date.UTC(
    Number(filled.year),
    Number(filled.month) - 1,
    Number(filled.day),
    Number(filled.hour),
    Number(filled.minute),
    Number(filled.second),
  );
  return asUtc - instant.getTime();
}

function nextCalendarDayIso(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + 1));
  const yy = dt.getUTCFullYear();
  const mm = String(dt.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(dt.getUTCDate()).padStart(2, "0");
  return `${yy}-${mm}-${dd}`;
}

/** Start of calendar day in timeZone, as UTC instant (ISO string). */
export function calendarDayStartUtcIso(
  isoDate: string,
  timeZone: string = APP_TIMEZONE,
): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  const utcGuess = Date.UTC(y, m - 1, d, 0, 0, 0, 0);
  const instant = new Date(utcGuess - timeZoneOffsetMs(timeZone, new Date(utcGuess)));
  return instant.toISOString();
}

/** End of calendar day (last ms before next local midnight) in timeZone, as UTC ISO. */
export function calendarDayEndUtcIso(
  isoDate: string,
  timeZone: string = APP_TIMEZONE,
): string {
  const nextLocalMidnight = new Date(
    calendarDayStartUtcIso(nextCalendarDayIso(isoDate), timeZone),
  ).getTime();
  return new Date(nextLocalMidnight - 1).toISOString();
}

export function validationPeriodToApiParams(dates: ValidationPeriodDates): {
  period_start?: string;
  period_end?: string;
} {
  if (!dates.from && !dates.to) return {};
  const out: { period_start?: string; period_end?: string } = {};
  if (dates.from) {
    out.period_start = calendarDayStartUtcIso(dates.from);
  }
  if (dates.to) {
    out.period_end = calendarDayEndUtcIso(dates.to);
  }
  return out;
}

/** True if saved_at (UTC instant) falls within URL calendar period in timeZone. */
export function utcInstantWithinValidationPeriod(
  savedAtUtcIso: string,
  dates: ValidationPeriodDates,
  timeZone: string = APP_TIMEZONE,
): boolean {
  const t = new Date(savedAtUtcIso).getTime();
  if (Number.isNaN(t)) return false;
  if (dates.from) {
    const start = new Date(calendarDayStartUtcIso(dates.from, timeZone)).getTime();
    if (t < start) return false;
  }
  if (dates.to) {
    const end = new Date(calendarDayEndUtcIso(dates.to, timeZone)).getTime();
    if (t > end) return false;
  }
  return true;
}

export function formatValidationPeriodLabel(dates: ValidationPeriodDates): string {
  if (!dates.from && !dates.to) {
    return "за всё время";
  }
  const fmt = (iso: string) => {
    const [y, m, d] = iso.split("-");
    return `${d}.${m}.${y}`;
  };
  if (dates.from && dates.to) {
    return `${fmt(dates.from)} — ${fmt(dates.to)}`;
  }
  if (dates.from) return `с ${fmt(dates.from)}`;
  return `по ${fmt(dates.to)}`;
}

export function savedResearchReturnToParam(validationDates: ValidationPeriodDates): string {
  return encodeURIComponent(validationPeriodHref(validationDates));
}

export function savedItemHrefWithReturn(
  item: { kind: "video" | "family"; id: number },
  validationDates: ValidationPeriodDates,
): string {
  const base =
    item.kind === "video" ? `/saved/videos/${item.id}` : `/saved/families/${item.id}`;
  const returnTo = savedResearchReturnToParam(validationDates);
  return `${base}?returnTo=${returnTo}`;
}
