"""Persist videos.list format check attempts per video (Stage 2.1 / 2.5)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.orm import VideoFormatEnrichmentAttempt
from app.services.metrics import ensure_utc
from app.services.video_format_outcomes import (
    OUTCOME_FAILED,
    OUTCOME_MISSING,
    OUTCOME_UNRESOLVED,
)

FORMAT_ENRICHMENT_RETRY_OUTCOMES = frozenset(
    {OUTCOME_MISSING, OUTCOME_FAILED, OUTCOME_UNRESOLVED},
)


def format_enrichment_retry_due(
    *,
    last_outcome: str | None,
    last_attempt_at: datetime | None,
    now: datetime,
    retry_after_hours: int,
) -> bool:
    """Missing/failed/unresolved attempts respect retry_after; others may proceed when format still needed."""
    if last_outcome is None or last_attempt_at is None:
        return True
    if last_outcome not in FORMAT_ENRICHMENT_RETRY_OUTCOMES:
        return True
    if retry_after_hours <= 0:
        return True
    return ensure_utc(last_attempt_at) <= ensure_utc(now) - timedelta(hours=retry_after_hours)


def record_format_enrichment_attempt(
    session: Session,
    *,
    video_id: str,
    outcome: str,
    attempted_at: datetime | None = None,
) -> None:
    stamp = attempted_at or datetime.now(timezone.utc)
    row = session.get(VideoFormatEnrichmentAttempt, video_id)
    if row is None:
        session.add(
            VideoFormatEnrichmentAttempt(
                video_id=video_id,
                last_attempt_at=stamp,
                last_outcome=outcome,
            ),
        )
    else:
        row.last_attempt_at = stamp
        row.last_outcome = outcome
    session.flush()
