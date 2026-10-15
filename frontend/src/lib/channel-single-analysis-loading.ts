/** Guards async channel-analysis operations against stale generation counters. */

export function isCurrentGeneration(generation: number, current: number): boolean {
  return generation === current;
}

/**
 * Focus compare runs only after feed enrich and when focus id actually changed
 * (initial enrich already includes the first focus from the URL).
 */
export function shouldRunFocusCompare(
  previousFocusVideoId: string,
  nextFocusVideoId: string,
  enrichedReady: boolean,
): boolean {
  if (!enrichedReady) {
    return false;
  }
  return previousFocusVideoId !== nextFocusVideoId;
}
