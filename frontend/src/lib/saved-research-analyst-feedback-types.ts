export type SavedResearchAnalystVerdict =
  | "USEFUL"
  | "NOT_RELEVANT"
  | "NOISE_OR_DUPLICATE"
  | "TOO_BROAD"
  | "NEEDS_RESEARCH";

export type SavedResearchFeedbackEntry = {
  id: number;
  entity_kind: "video" | "family";
  entity_id: number;
  verdict: SavedResearchAnalystVerdict;
  reason: string | null;
  created_at: string;
};

export type SavedResearchFeedbackHistory = {
  latest: SavedResearchFeedbackEntry | null;
  items: SavedResearchFeedbackEntry[];
  total: number;
  limit: number;
  offset: number;
};

export type SavedResearchFeedbackPayload = {
  verdict: SavedResearchAnalystVerdict;
  reason?: string | null;
};
