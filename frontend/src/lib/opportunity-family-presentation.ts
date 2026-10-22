import type { AttentionPatternFamily } from "@/lib/attention-types";

export function familyPresentationTier(family: AttentionPatternFamily) {
  return family.opportunity_presentation_tier ?? "search_collection";
}

export function isRepeatingIdeaFamily(family: AttentionPatternFamily) {
  return familyPresentationTier(family) === "repeating_idea";
}

export function isNeedsReviewFamily(family: AttentionPatternFamily) {
  return familyPresentationTier(family) === "needs_review";
}

export function isSearchCollectionFamily(family: AttentionPatternFamily) {
  return familyPresentationTier(family) === "search_collection";
}

export function familySectionBadge(family: AttentionPatternFamily): string {
  switch (familyPresentationTier(family)) {
    case "repeating_idea":
      return "Повторяющаяся идея";
    case "needs_review":
      return "Требует проверки";
    default:
      return "Подборка поиска";
  }
}

export const WINNER_FOCUS_HASH_PREFIX = "winner-";

export function winnerFeedHref(videoId: string): string {
  return `/opportunities#${WINNER_FOCUS_HASH_PREFIX}${encodeURIComponent(videoId)}`;
}

/** @deprecated use winnerFeedHref */
export function winnerFeedAnchor(videoId: string): string {
  return winnerFeedHref(videoId);
}

export function parseWinnerVideoIdFromHash(hash: string): string | null {
  const raw = hash.replace(/^#/, "").trim();
  if (!raw.startsWith(WINNER_FOCUS_HASH_PREFIX)) {
    return null;
  }
  const encoded = raw.slice(WINNER_FOCUS_HASH_PREFIX.length);
  if (!encoded) {
    return null;
  }
  try {
    return decodeURIComponent(encoded);
  } catch {
    return null;
  }
}
