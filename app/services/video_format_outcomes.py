"""videos.list format verification outcome labels (Stage 2.5)."""

from __future__ import annotations

from app.models.orm import VideoFormat

OUTCOME_CONFIRMED_REGULAR = "confirmed_regular"
OUTCOME_STREAM = "stream"
OUTCOME_SHORT = "short"
OUTCOME_MISSING = "missing"
OUTCOME_FAILED = "failed"
OUTCOME_UNRESOLVED = "unresolved"
# Legacy attempt label (live + short were grouped before Stage 2.5 metrics split)
OUTCOME_LIVE = "live_or_broadcast"


def classify_api_format_outcome(
    *,
    previous: VideoFormat,
    current: VideoFormat,
    inferred: VideoFormat | None,
    had_details: bool,
) -> str:
    if not had_details:
        return OUTCOME_MISSING
    if inferred is None:
        return OUTCOME_UNRESOLVED
    if current == VideoFormat.LIVE or inferred == VideoFormat.LIVE:
        return OUTCOME_STREAM
    if current == VideoFormat.SHORT or inferred == VideoFormat.SHORT:
        return OUTCOME_SHORT
    if current in (VideoFormat.MEDIUM, VideoFormat.LONG):
        return OUTCOME_CONFIRMED_REGULAR
    return OUTCOME_UNRESOLVED
