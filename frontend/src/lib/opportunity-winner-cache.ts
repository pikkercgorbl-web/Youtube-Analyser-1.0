import type { AttentionSummary, AttentionVideoWinner } from "@/lib/attention-types";

const WINNER_PREFIX = "opportunity-winner:";
const META_KEY = "opportunity-attention-meta";

export function stashWinnerForDetail(video: AttentionVideoWinner): void {
  if (typeof sessionStorage === "undefined") {
    return;
  }
  try {
    sessionStorage.setItem(`${WINNER_PREFIX}${video.video_id}`, JSON.stringify(video));
  } catch {
    /* quota or private mode */
  }
}

export function readStashedWinner(videoId: string): AttentionVideoWinner | null {
  if (typeof sessionStorage === "undefined") {
    return null;
  }
  try {
    const raw = sessionStorage.getItem(`${WINNER_PREFIX}${videoId}`);
    if (!raw) {
      return null;
    }
    return JSON.parse(raw) as AttentionVideoWinner;
  } catch {
    return null;
  }
}

export function stashAttentionMeta(summary: AttentionSummary): void {
  if (typeof sessionStorage === "undefined") {
    return;
  }
  try {
    sessionStorage.setItem(
      META_KEY,
      JSON.stringify({
        computed_at: summary.computed_at,
        window_hours: summary.window_hours,
        window_start: summary.window_start,
        window_end: summary.window_end,
      }),
    );
  } catch {
    /* ignore */
  }
}

export function readStashedAttentionMeta(): {
  computed_at: string;
  window_hours: number;
  window_start: string;
  window_end: string;
} | null {
  if (typeof sessionStorage === "undefined") {
    return null;
  }
  try {
    const raw = sessionStorage.getItem(META_KEY);
    if (!raw) {
      return null;
    }
    return JSON.parse(raw) as {
      computed_at: string;
      window_hours: number;
      window_start: string;
      window_end: string;
    };
  } catch {
    return null;
  }
}
