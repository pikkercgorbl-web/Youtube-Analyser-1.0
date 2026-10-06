/**
 * Stage 1.22C integration point — Saved Topics / Watchlist.
 *
 * Bookmark identity is backend `family_key` (Pattern Family).
 * Underlying Pattern rows remain audit-only (`pattern_key`).
 *
 * Future SavedTopic must support:
 * - Frozen Snapshot (Attention run_id + family_key at save time)
 * - Live State
 * - History
 * - User status
 * - Notes / tags
 *
 * Do not persist in localStorage.
 */

export const SAVED_TOPICS_STAGE = "1.22C";

export const SAVED_TOPIC_DISABLED_HINT = "Закладки будут подключены на следующем этапе";

export type SavedTopicDraft = {
  familyKey: string;
  runId: string | null;
};

export function savedTopicAffordance(_draft: SavedTopicDraft): {
  enabled: boolean;
  hint: string;
} {
  return { enabled: false, hint: SAVED_TOPIC_DISABLED_HINT };
}
