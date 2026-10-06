"""Persist keyword scan runs and discovery hits (Stage 1.16A)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from sqlalchemy.orm import Session

from app.integrations.youtube.client import LiveBroadcastStatus, VideoSearchModel, video_is_stream_content
from app.models.orm import KeywordDiscoveryHit, KeywordScanRun
from app.services.discovery_keyword_scan import KeywordDiscoveryScanResult
from app.services.radar_candidate import RadarCandidate


def _content_format_label(video: VideoSearchModel) -> str:
    if video.is_short:
        return "short"
    if video.is_live or video_is_stream_content(video):
        return "live"
    if video.live_broadcast_status == LiveBroadcastStatus.UNKNOWN:
        return "unknown"
    return "regular"


def _candidate_for_video(candidates: list[RadarCandidate], video_id: str) -> RadarCandidate | None:
    matched = [c for c in candidates if c.video_id == video_id]
    if not matched:
        return None
    return matched[-1]


def _within_keyword_duplicate_counts(candidates: list[RadarCandidate]) -> Counter[str]:
    return Counter(c.video_id for c in candidates)


def persist_keyword_scan_run(
    session: Session,
    *,
    keyword_id: int,
    discovery_run_id: str,
    started_at: datetime,
    finished_at: datetime,
    status: str,
    raw_candidates: int,
    unique_candidates: int,
    within_keyword_duplicate_candidates: int,
    cross_keyword_duplicate_candidates: int,
    persisted_videos: int,
    qualification_passed: int,
    qualification_rejected: int,
    error_summary: str | None,
    runtime_seconds: float,
) -> KeywordScanRun:
    row = KeywordScanRun(
        keyword_id=keyword_id,
        discovery_run_id=discovery_run_id,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        raw_candidates=raw_candidates,
        unique_candidates=unique_candidates,
        within_keyword_duplicate_candidates=within_keyword_duplicate_candidates,
        cross_keyword_duplicate_candidates=cross_keyword_duplicate_candidates,
        persisted_videos=persisted_videos,
        qualification_passed=qualification_passed,
        qualification_rejected=qualification_rejected,
        error_summary=error_summary,
        runtime_seconds=runtime_seconds,
    )
    session.add(row)
    session.flush()
    return row


def persist_keyword_discovery_hits(
    session: Session,
    *,
    keyword_id: int,
    discovery_run_id: str,
    discovered_at: datetime,
    scan: KeywordDiscoveryScanResult,
    cycle_video_ids_seen: set[str],
    video_ids_existing_before_cycle: frozenset[str],
) -> tuple[int, int]:
    """
    Persist one hit per unique video for this keyword in this cycle.

    Returns (cross_keyword_duplicate_count, persisted_for_monitoring_count).
    """
    raw_counts = _within_keyword_duplicate_counts(scan.candidates)
    cross_dup = 0
    persisted_hits = 0

    for video in scan.unique_videos:
        candidate = _candidate_for_video(scan.candidates, video.video_id)
        channel_id = (video.channel_id or "").strip() or None
        cross = video.video_id in cycle_video_ids_seen
        if cross:
            cross_dup += 1
        cycle_video_ids_seen.add(video.video_id)

        qualification_state = candidate.qualification_state if candidate else "pending"
        first_failure = candidate.first_failure_reason if candidate else None
        vph = None
        views = max(video.views_count, 0)
        if candidate is not None:
            vph = candidate.vph_at_t0 if candidate.vph_at_t0 is not None else candidate.vph
            views = candidate.views or views

        session.add(
            KeywordDiscoveryHit(
                keyword_id=keyword_id,
                video_id=video.video_id,
                discovery_run_id=discovery_run_id,
                discovered_at=discovered_at,
                channel_id=channel_id,
                was_within_keyword_duplicate=raw_counts.get(video.video_id, 0) > 1,
                was_cross_keyword_duplicate=cross,
                video_existed_before_discovery=video.video_id in video_ids_existing_before_cycle,
                content_format=_content_format_label(video),
                views_at_discovery=views if views > 0 else None,
                vph_at_discovery=vph,
                qualification_state=qualification_state,
                first_failure_reason=first_failure,
                persisted_for_monitoring=False,
            ),
        )

    session.flush()
    return cross_dup, persisted_hits


def mark_hits_persisted_for_monitoring(
    session: Session,
    *,
    keyword_id: int,
    discovery_run_id: str,
    video_ids: set[str],
) -> None:
    if not video_ids:
        return
    from sqlalchemy import select

    hits = session.scalars(
        select(KeywordDiscoveryHit).where(
            KeywordDiscoveryHit.keyword_id == keyword_id,
            KeywordDiscoveryHit.discovery_run_id == discovery_run_id,
            KeywordDiscoveryHit.video_id.in_(video_ids),
        ),
    ).all()
    for hit in hits:
        hit.persisted_for_monitoring = True
    session.flush()
