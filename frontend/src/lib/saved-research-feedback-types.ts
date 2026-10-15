export type EvidenceState = "validated" | "pending" | "insufficient";

export type SavedResearchFeedbackItem = {
  kind: "video" | "family";
  id: number;
  title?: string;
  label?: string;
  status: string;
  updated_at: string;
  validation: Record<string, unknown>;
};

export type SavedResearchFeedbackOverview = {
  status_counts: Record<string, number>;
  evidence_summary: Record<EvidenceState, number>;
  recently_updated: SavedResearchFeedbackItem[];
  measurable_growth_videos: SavedResearchFeedbackItem[];
  insufficient_evidence: SavedResearchFeedbackItem[];
  videos: { items: SavedResearchFeedbackItem[]; total: number; limit: number; offset: number };
  families: { items: SavedResearchFeedbackItem[]; total: number; limit: number; offset: number };
  interpretation_notes: string[];
};

export type SavedResearchDecisionEvent = {
  id: number;
  entity_kind: string;
  entity_id: number;
  occurred_at: string;
  event_type: string;
  payload: Record<string, unknown>;
};
