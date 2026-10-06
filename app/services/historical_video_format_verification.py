"""Dry-run plan for verifying persisted MEDIUM/LONG via videos.list (Stage 2.1)."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import (
    AttentionPatternFamilyRow,
    AttentionRun,
    AttentionVideoWinnerRow,
    Video,
    VideoFormat,
)
from app.integrations.youtube.client import YouTubeVideoDetails
from app.services.video_format_batch_apply import apply_format_details_for_batch
from app.services.video_format_from_api import chunk_video_ids
from app.services.video_format_outcomes import (
    OUTCOME_CONFIRMED_REGULAR,
    OUTCOME_LIVE,
    OUTCOME_MISSING,
    OUTCOME_UNRESOLVED,
)


@dataclass
class HistoricalFormatVerificationPlan:
    video_ids: tuple[str, ...] = ()
    sources: dict[str, str] = field(default_factory=dict)
    batch_count: int = 0
    persisted_winner_count: int = 0
    computed_winner_count: int = 0
    family_representative_count: int = 0


def build_historical_format_verification_plan(
    session: Session,
    *,
    computed_winner_ids: list[str] | tuple[str, ...] | None = None,
    family_representative_ids: list[str] | tuple[str, ...] | None = None,
    include_formats: tuple[VideoFormat, ...] = (VideoFormat.MEDIUM, VideoFormat.LONG),
) -> HistoricalFormatVerificationPlan:
    sources: dict[str, str] = {}
    latest_run = session.scalar(
        select(AttentionRun.run_id).order_by(AttentionRun.computed_at.desc()).limit(1),
    )
    persisted: list[str] = []
    if latest_run:
        persisted = list(
            session.scalars(
                select(AttentionVideoWinnerRow.video_id).where(
                    AttentionVideoWinnerRow.run_id == latest_run,
                ),
            ).all(),
        )
    for vid in persisted:
        sources.setdefault(vid, "persisted_winner")

    for vid in computed_winner_ids or ():
        sources.setdefault(vid, "computed_winner")

    for vid in family_representative_ids or ():
        sources.setdefault(vid, "family_representative")

    if latest_run and not family_representative_ids:
        from app.models.orm import AttentionPatternFamilyVideoRow

        family_rows = session.scalars(
            select(AttentionPatternFamilyRow.family_key).where(
                AttentionPatternFamilyRow.run_id == latest_run,
            ).limit(50),
        ).all()
        for family_key in family_rows:
            vid = session.scalar(
                select(AttentionPatternFamilyVideoRow.video_id)
                .where(
                    AttentionPatternFamilyVideoRow.run_id == latest_run,
                    AttentionPatternFamilyVideoRow.family_key == family_key,
                )
                .limit(1),
            )
            if vid:
                sources.setdefault(str(vid), "family_representative")

    candidate_ids = list(sources.keys())
    if not candidate_ids:
        return HistoricalFormatVerificationPlan()

    rows = session.scalars(select(Video).where(Video.id.in_(candidate_ids))).all()
    by_id = {row.id: row for row in rows}
    ordered: list[str] = []
    for vid in candidate_ids:
        row = by_id.get(vid)
        if row is None:
            continue
        if row.content_format not in include_formats:
            continue
        if vid not in ordered:
            ordered.append(vid)

    batches = chunk_video_ids(ordered, batch_size=50)
    return HistoricalFormatVerificationPlan(
        video_ids=tuple(ordered),
        sources={vid: sources[vid] for vid in ordered},
        batch_count=len(batches),
        persisted_winner_count=sum(1 for v in ordered if sources.get(v) == "persisted_winner"),
        computed_winner_count=sum(1 for v in ordered if sources.get(v) == "computed_winner"),
        family_representative_count=sum(1 for v in ordered if sources.get(v) == "family_representative"),
    )


@dataclass
class HistoricalFormatVerificationReport:
    api_batch_count: int = 0
    requested: int = 0
    confirmed_regular: int = 0
    stream: int = 0
    short: int = 0
    failed: int = 0
    missing: int = 0
    medium_long_to_live: int = 0
    outcomes_by_video_id: dict[str, str] = field(default_factory=dict)
    transitions_to_live: list[tuple[str, str, str]] = field(default_factory=list)


def apply_historical_format_verification(
    session: Session,
    youtube_client,
    plan: HistoricalFormatVerificationPlan,
    *,
    record_attempts: bool = True,
) -> HistoricalFormatVerificationReport:
    """Apply videos.list format updates for planned MEDIUM/LONG rows (separate from Attention)."""
    report = HistoricalFormatVerificationReport(requested=len(plan.video_ids))
    if not plan.video_ids:
        return report
    for batch in chunk_video_ids(list(plan.video_ids), batch_size=50):
        report.api_batch_count += 1
        details_list = youtube_client.get_videos(batch)
        by_id = {d.video_id: d for d in details_list if isinstance(d, YouTubeVideoDetails)}
        apply_report = apply_format_details_for_batch(
            session,
            batch,
            by_id,
            record_attempts=record_attempts,
        )
        report.missing += apply_report.missing
        report.confirmed_regular += apply_report.confirmed_regular
        report.stream += apply_report.stream
        report.short += apply_report.short
        report.failed += apply_report.failed
        report.outcomes_by_video_id.update(apply_report.outcomes_by_video_id)
        videos_by_id = {
            row.id: row for row in session.scalars(select(Video).where(Video.id.in_(batch))).all()
        }
        for vid in batch:
            row = videos_by_id.get(vid)
            if row is None:
                continue
            if row.content_format == VideoFormat.LIVE and apply_report.outcomes_by_video_id.get(vid) == OUTCOME_LIVE:
                report.medium_long_to_live += 1
                report.transitions_to_live.append((vid, VideoFormat.MEDIUM.value, row.content_format.value))
    session.flush()
    return report


def verify_video_id_batches(
    session: Session,
    youtube_client,
    video_ids: list[str],
    *,
    record_attempts: bool = True,
) -> HistoricalFormatVerificationReport:
    plan = HistoricalFormatVerificationPlan(video_ids=tuple(video_ids), batch_count=0)
    if video_ids:
        plan.batch_count = len(chunk_video_ids(video_ids, batch_size=50))
    return apply_historical_format_verification(
        session,
        youtube_client,
        plan,
        record_attempts=record_attempts,
    )
