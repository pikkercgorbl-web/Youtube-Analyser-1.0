"""Batch apply videos.list results to Video rows (Stage 2.5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.youtube.client import YouTubeVideoDetails
from app.models.orm import Video, VideoFormat
from app.services.video_format_outcomes import (
    OUTCOME_CONFIRMED_REGULAR,
    OUTCOME_FAILED,
    OUTCOME_LIVE,
    OUTCOME_MISSING,
    OUTCOME_SHORT,
    OUTCOME_STREAM,
    OUTCOME_UNRESOLVED,
    classify_api_format_outcome,
)
from app.services.format_enrichment_attempts import record_format_enrichment_attempt
from app.services.video_format_from_api import infer_video_format_from_details
from app.services.video_format_persistence import apply_api_details_to_video_content_format


@dataclass
class FormatBatchApplyReport:
    processed_ids: int = 0
    confirmed_regular: int = 0
    stream: int = 0
    short: int = 0
    missing: int = 0
    failed: int = 0
    outcomes_by_video_id: dict[str, str] = field(default_factory=dict)

    @property
    def live_or_broadcast(self) -> int:
        """Legacy: stream + short."""
        return self.stream + self.short


def _load_videos(session: Session, video_ids: list[str]) -> dict[str, Video]:
    if not video_ids:
        return {}
    rows = session.scalars(select(Video).where(Video.id.in_(video_ids))).all()
    return {row.id: row for row in rows}


def apply_format_details_for_batch(
    session: Session,
    video_ids: list[str],
    details_by_id: dict[str, YouTubeVideoDetails],
    *,
    attempted_at: datetime | None = None,
    record_attempts: bool = True,
) -> FormatBatchApplyReport:
    stamp = attempted_at or datetime.now(timezone.utc)
    report = FormatBatchApplyReport(processed_ids=len(video_ids))
    videos_by_id = _load_videos(session, video_ids)

    for vid in video_ids:
        row = videos_by_id.get(vid)
        if row is None:
            report.missing += 1
            report.outcomes_by_video_id[vid] = OUTCOME_MISSING
            if record_attempts:
                record_format_enrichment_attempt(session, video_id=vid, outcome=OUTCOME_MISSING, attempted_at=stamp)
            continue
        details = details_by_id.get(vid)
        if details is None:
            report.missing += 1
            report.outcomes_by_video_id[vid] = OUTCOME_MISSING
            if record_attempts:
                record_format_enrichment_attempt(session, video_id=vid, outcome=OUTCOME_MISSING, attempted_at=stamp)
            continue
        previous = row.content_format
        inferred = infer_video_format_from_details(details)
        apply_api_details_to_video_content_format(row, details)
        outcome = classify_api_format_outcome(
            previous=previous,
            current=row.content_format,
            inferred=inferred,
            had_details=True,
        )
        report.outcomes_by_video_id[vid] = outcome
        if outcome == OUTCOME_CONFIRMED_REGULAR:
            report.confirmed_regular += 1
        elif outcome == OUTCOME_STREAM:
            report.stream += 1
        elif outcome == OUTCOME_SHORT:
            report.short += 1
        elif outcome == OUTCOME_MISSING:
            report.missing += 1
        elif outcome in (OUTCOME_UNRESOLVED, OUTCOME_FAILED):
            report.failed += 1
        elif outcome == OUTCOME_LIVE:
            report.stream += 1
        if record_attempts:
            record_format_enrichment_attempt(session, video_id=vid, outcome=outcome, attempted_at=stamp)

    session.flush()
    return report


def video_needs_format_enrichment(
    *,
    content_format: VideoFormat,
    video_id: str,
    confirmed_regular_ids: frozenset[str],
    last_outcome: str | None,
) -> bool:
    if content_format in (VideoFormat.SHORT, VideoFormat.LIVE):
        return False
    if last_outcome in (
        OUTCOME_LIVE,
        OUTCOME_STREAM,
        OUTCOME_SHORT,
        "live_or_broadcast",
        "updated_short",
        "updated_live",
    ):
        return False
    if content_format == VideoFormat.UNKNOWN:
        return True
    if content_format in (VideoFormat.MEDIUM, VideoFormat.LONG):
        return video_id not in confirmed_regular_ids
    return False
