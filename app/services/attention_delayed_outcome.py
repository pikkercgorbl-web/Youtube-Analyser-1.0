"""Per-video 72h delayed-outcome state using existing horizon matching."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models.orm import KeywordDiscoveryHit, VideoSnapshot
from app.services.attention_engine_types import DelayedOutcomeState
from app.services.keyword_performance_evaluation import (
    HORIZON_HOURS,
    HORIZON_SNAPSHOT_TOLERANCE_HOURS,
    KeywordVideoBaseline,
    match_horizon_outcome,
)
from app.services.metrics import ensure_utc


def delayed_outcome_for_video(
    *,
    video_id: str,
    hits: list[KeywordDiscoveryHit],
    snapshots: list[VideoSnapshot],
    now: datetime,
    horizon_hours: int = HORIZON_HOURS,
    tolerance_hours: float = HORIZON_SNAPSHOT_TOLERANCE_HOURS,
) -> tuple[DelayedOutcomeState, int | None]:
    """
    Prefer the earliest discovery hit with views_at_discovery.

    missing stays missing (no snapshot in the 72h tolerance window).
    No discovery provenance → unavailable, not pending.
    """
    if not hits:
        return "unavailable", None
    usable = [h for h in hits if h.views_at_discovery is not None]
    if not usable:
        return "unavailable", None
    hit = min(usable, key=lambda row: (ensure_utc(row.discovered_at), row.id))
    discovery_at = ensure_utc(hit.discovered_at)
    reference = ensure_utc(now)
    if reference < discovery_at + timedelta(hours=horizon_hours):
        return "pending", None
    baseline = KeywordVideoBaseline(
        keyword_id=hit.keyword_id,
        video_id=video_id,
        discovery_at=hit.discovered_at,
        views_at_discovery=hit.views_at_discovery,
        vph_at_discovery=hit.vph_at_discovery,
    )
    by_video = {video_id: snapshots}
    outcome = match_horizon_outcome(
        baseline,
        by_video,
        tolerance_hours=tolerance_hours,
    )
    if outcome is None:
        return "missing", None
    if outcome.absolute_view_growth > 0:
        return "confirmed", outcome.absolute_view_growth
    return "not_confirmed", outcome.absolute_view_growth
