"""Plan discovery-delay outcome snapshot captures (Stage 1.20E.2). Read-only planning."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import KeywordDiscoveryHit, Video
from app.services.keyword_performance_evaluation import (
    HORIZON_HOURS,
    HORIZON_SNAPSHOT_TOLERANCE_HOURS,
)
from app.services.delayed_outcome_capture_types import (
    DelayedOutcomeCapturePlan,
    OutcomeAttributionMode,
    OutcomeCaptureState,
    OutcomeObservationPlan,
    OutcomeObservationRecord,
    OutcomeVideoFetchCandidate,
)
from app.services.keyword_performance_evaluation import (
    KeywordVideoBaseline,
    _first_discovery_owner,
    _first_hit_per_keyword_video,
    attributed_videos_for_keyword,
    match_horizon_outcome,
)
from app.services.metrics import ensure_utc


def _outcome_window(
    discovered_at: datetime,
    *,
    horizon_hours: int = HORIZON_HOURS,
    tolerance_hours: float = HORIZON_SNAPSHOT_TOLERANCE_HOURS,
) -> tuple[datetime, datetime, datetime]:
    target = ensure_utc(discovered_at) + timedelta(hours=horizon_hours)
    tolerance = timedelta(hours=tolerance_hours)
    return target, target - tolerance, target + tolerance


def _is_satisfied(
    record: OutcomeObservationRecord,
    snapshots_by_video: dict[str, list],
    *,
    tolerance_hours: float = HORIZON_SNAPSHOT_TOLERANCE_HOURS,
) -> bool:
    if record.views_at_discovery is None:
        return False
    baseline = KeywordVideoBaseline(
        keyword_id=record.keyword_id,
        video_id=record.video_id,
        discovery_at=record.discovered_at,
        views_at_discovery=record.views_at_discovery,
        vph_at_discovery=None,
    )
    return match_horizon_outcome(
        baseline,
        snapshots_by_video,
        tolerance_hours=tolerance_hours,
    ) is not None


def classify_outcome_observation(
    record: OutcomeObservationRecord,
    *,
    reference: datetime,
    snapshots_by_video: dict[str, list],
    horizon_hours: int = HORIZON_HOURS,
    tolerance_hours: float = HORIZON_SNAPSHOT_TOLERANCE_HOURS,
) -> OutcomeObservationPlan:
    now = ensure_utc(reference)
    target_at, window_start, window_end = _outcome_window(
        record.discovered_at,
        horizon_hours=horizon_hours,
        tolerance_hours=tolerance_hours,
    )
    if _is_satisfied(record, snapshots_by_video, tolerance_hours=tolerance_hours):
        state: OutcomeCaptureState = "satisfied"
    elif now > window_end:
        state = "expired"
    elif now < window_start:
        state = "pending"
    elif now <= target_at:
        state = "capture_due"
    else:
        state = "capture_overdue"

    hours_left: float | None = None
    if now <= window_end:
        hours_left = round((window_end - now).total_seconds() / 3600.0, 4)

    return OutcomeObservationPlan(
        keyword_id=record.keyword_id,
        video_id=record.video_id,
        discovered_at=ensure_utc(record.discovered_at),
        target_at=target_at,
        window_start=window_start,
        window_end=window_end,
        state=state,
        hours_until_window_end=hours_left,
    )


def load_attributed_outcome_observations(
    session: Session,
    *,
    attribution_mode: OutcomeAttributionMode = "all_hits",
) -> list[OutcomeObservationRecord]:
    hits = list(session.scalars(select(KeywordDiscoveryHit)).all())
    if not hits:
        return []
    first_owner = _first_discovery_owner(hits)
    baselines_map = _first_hit_per_keyword_video(hits)
    keyword_ids = sorted({hit.keyword_id for hit in hits})
    hits_by_keyword: dict[int, list[KeywordDiscoveryHit]] = {}
    for hit in hits:
        hits_by_keyword.setdefault(hit.keyword_id, []).append(hit)

    records: list[OutcomeObservationRecord] = []
    for kid in keyword_ids:
        vids = attributed_videos_for_keyword(
            kid,
            mode=attribution_mode,
            hits_for_keyword=hits_by_keyword.get(kid, []),
            first_owner=first_owner,
        )
        for vid in sorted(vids):
            hit = baselines_map.get((kid, vid))
            if hit is None:
                continue
            records.append(
                OutcomeObservationRecord(
                    keyword_id=kid,
                    video_id=vid,
                    channel_id=hit.channel_id,
                    discovered_at=hit.discovered_at,
                    views_at_discovery=hit.views_at_discovery,
                ),
            )
    return records


def plan_delayed_outcome_capture(
    session: Session,
    *,
    reference: datetime,
    attribution_mode: OutcomeAttributionMode = "all_hits",
    horizon_hours: int = HORIZON_HOURS,
    tolerance_hours: float = HORIZON_SNAPSHOT_TOLERANCE_HOURS,
) -> DelayedOutcomeCapturePlan:
    records = load_attributed_outcome_observations(session, attribution_mode=attribution_mode)
    ref = ensure_utc(reference)
    video_ids_needing_snapshots = sorted(
        {
            row.video_id
            for row in records
            if ref >= _outcome_window(row.discovered_at, horizon_hours=horizon_hours, tolerance_hours=tolerance_hours)[1]
        },
    )
    snapshots_by_video: dict[str, list] = {}
    if video_ids_needing_snapshots:
        from app.services.video_snapshot_storage import get_snapshots_for_videos

        for snap in get_snapshots_for_videos(session, video_ids_needing_snapshots):
            snapshots_by_video.setdefault(snap.video_id, []).append(snap)

    observations: list[OutcomeObservationPlan] = []
    counts = {
        "pending": 0,
        "capture_due": 0,
        "capture_overdue": 0,
        "satisfied": 0,
        "expired": 0,
    }
    for record in records:
        plan_row = classify_outcome_observation(
            record,
            reference=reference,
            snapshots_by_video=snapshots_by_video,
            horizon_hours=horizon_hours,
            tolerance_hours=tolerance_hours,
        )
        observations.append(plan_row)
        counts[plan_row.state] += 1

    due_by_video: dict[str, list[OutcomeObservationPlan]] = {}
    channel_by_video: dict[str, str | None] = {r.video_id: r.channel_id for r in records}
    for row in observations:
        if row.state not in ("capture_due", "capture_overdue"):
            continue
        due_by_video.setdefault(row.video_id, []).append(row)

    candidates: list[OutcomeVideoFetchCandidate] = []
    for video_id, rows in due_by_video.items():
        min_hours = min(r.hours_until_window_end or 0.0 for r in rows)
        candidates.append(
            OutcomeVideoFetchCandidate(
                video_id=video_id,
                channel_id=channel_by_video.get(video_id),
                priority_hours_to_window_end=min_hours,
                observation_count=len(rows),
                states=tuple(sorted({r.state for r in rows})),
            ),
        )
    candidates.sort(
        key=lambda c: (c.priority_hours_to_window_end, c.video_id),
    )

    return DelayedOutcomeCapturePlan(
        attribution_mode=attribution_mode,
        reference_at=ensure_utc(reference),
        attributed_observation_count=len(records),
        pending_count=counts["pending"],
        capture_due_count=counts["capture_due"],
        capture_overdue_count=counts["capture_overdue"],
        satisfied_count=counts["satisfied"],
        expired_count=counts["expired"],
        unique_due_video_count=len(candidates),
        observations=observations,
        fetch_candidates=candidates,
    )


def load_published_at_by_video(session: Session, video_ids: list[str]) -> dict[str, datetime | None]:
    if not video_ids:
        return {}
    rows = session.execute(
        select(Video.id, Video.published_at).where(Video.id.in_(video_ids)),
    ).all()
    return {str(vid): pub for vid, pub in rows}
