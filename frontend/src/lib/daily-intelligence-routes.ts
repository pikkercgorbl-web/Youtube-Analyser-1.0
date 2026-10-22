/** Path segments for Next.js dynamic routes (encodeURIComponent). */
export function dailyIntelligenceDayHref(reportDate: string): string {
  return `/daily-intelligence?date=${encodeURIComponent(reportDate)}`;
}

export function dailyIntelligenceWinnerDetailHref(
  reportDate: string,
  videoId: string,
): string {
  return `/daily-intelligence/${encodeURIComponent(reportDate)}/winners/${encodeURIComponent(videoId)}`;
}

export function dailyIntelligenceFamilyDetailHref(
  reportDate: string,
  familyKey: string,
): string {
  return `/daily-intelligence/${encodeURIComponent(reportDate)}/families/${encodeURIComponent(familyKey)}`;
}

export function decodeDailyIntelligenceRouteParam(value: string): string {
  return decodeURIComponent(value);
}
