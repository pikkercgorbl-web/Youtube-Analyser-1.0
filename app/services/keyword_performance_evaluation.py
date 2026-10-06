"""Batched keyword performance evaluation (Stage 1.18B)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import KeywordDiscoveryHit, KeywordScanRun, TargetKeyword, Video, VideoFormat, VideoSnapshot
from app.services.breakout_ranking_service import (
    BREAKOUT_RANK_VERSION,
    breakout_fundamental_eligibility,
    rank_breakout_v1,
)
from app.services.metrics import ensure_utc, utc_now
from app.services.monitoring_tier_budget_policy import MonitoringTier, MonitoringTierPolicy, assign_monitoring_tiers
from app.services.monitoring_video_source import MonitoredVideoState, _state_from_video
from app.services.radar_candidate_analysis import _percentile
from app.services.video_snapshot_storage import get_latest_snapshots_for_videos, get_snapshots_for_videos

HORIZON_HOURS = 72
HORIZON_SNAPSHOT_TOLERANCE_HOURS = 12

AttributionMode = Literal["all_hits", "first_discovery"]


@dataclass(frozen=True, slots=True)
class KeywordEvaluationOptions:
    """Read-path toggles (Stage 1.18D1); default preserves full 1.18B response."""

    include_breakout: bool = True
    include_delayed: bool = True


@dataclass(frozen=True, slots=True)
class GlobalBreakoutBundle:
    breakout_map: dict[str, VideoBreakoutInfo]
    global_eligible_video_count: int
    states_by_id: dict[str, MonitoredVideoState]


@dataclass(frozen=True, slots=True)
class KeywordEvaluationContext:
    evaluated_at: datetime
    attribution_mode: AttributionMode
    window_from: datetime | None
    window_to: datetime | None
    ranking_version: str
    global_eligible_video_count: int
    horizon_hours: int
    horizon_snapshot_tolerance_hours: int
    top_decile_rank_cutoff: int


@dataclass(frozen=True, slots=True)
class VideoBreakoutInfo:
    eligible: bool
    rank: int | None
    current_vph: float | None


@dataclass(frozen=True, slots=True)
class HorizonOutcome:
    discovery_at: datetime
    views_at_discovery: int
    outcome_views: int
    absolute_view_growth: int
    actual_elapsed_hours: float
    snapshot_captured_at: datetime


@dataclass(frozen=True, slots=True)
class KeywordVideoBaseline:
    keyword_id: int
    video_id: str
    discovery_at: datetime
    views_at_discovery: int | None
    vph_at_discovery: float | None


@dataclass
class EvidenceDetail:
    scan_count: int
    unique_video_count: int
    breakout_eligible_video_count: int
    observed_72h_video_count: int


def _time_clauses(column, from_ts: datetime | None, to_ts: datetime | None) -> list:
    clauses = []
    if from_ts is not None:
        clauses.append(column >= ensure_utc(from_ts))
    if to_ts is not None:
        clauses.append(column <= ensure_utc(to_ts))
    return clauses


def build_global_breakout_bundle(
    session: Session,
    *,
    evaluated_at: datetime | None = None,
) -> GlobalBreakoutBundle:
    """
    One monitoring-pool pass: regular videos + latest snapshot row per video only.

    Global breakout denominator/ranks require the full monitorable pool — not
    keyword-attributed subsets.
    """
    reference = evaluated_at or utc_now()
    videos = list(
        session.scalars(
            select(Video)
            .where(Video.content_format.not_in((VideoFormat.SHORT, VideoFormat.LIVE)))
            .order_by(Video.id.asc()),
        ).all(),
    )
    video_ids = [video.id for video in videos]
    latest_by_id = get_latest_snapshots_for_videos(session, video_ids)
    states = [
        _state_from_video(video, now=reference, latest_snapshot=latest_by_id.get(video.id))
        for video in videos
    ]
    views_by_id: dict[str, int | None] = {
        vid: int(snap.views) if snap.views is not None else None
        for vid, snap in latest_by_id.items()
    }
    for state in states:
        views_by_id.setdefault(state.video_id, None)
    ranked = rank_breakout_v1(states, views_by_video_id=views_by_id)
    rank_by_id = {item.video_id: item.rank for item in ranked}
    tier_cfg = MonitoringTierPolicy()
    info: dict[str, VideoBreakoutInfo] = {}
    for state in states:
        ok, _ = breakout_fundamental_eligibility(state, max_age_monitoring_hours=tier_cfg.max_age_monitoring_hours)
        info[state.video_id] = VideoBreakoutInfo(
            eligible=ok,
            rank=rank_by_id.get(state.video_id),
            current_vph=state.raw_vph,
        )
    return GlobalBreakoutBundle(
        breakout_map=info,
        global_eligible_video_count=len(ranked),
        states_by_id={state.video_id: state for state in states},
    )


def build_global_breakout_map(
    session: Session,
    *,
    evaluated_at: datetime | None = None,
) -> tuple[dict[str, VideoBreakoutInfo], int]:
    bundle = build_global_breakout_bundle(session, evaluated_at=evaluated_at)
    return bundle.breakout_map, bundle.global_eligible_video_count


def _first_hit_per_keyword_video(hits: list[KeywordDiscoveryHit]) -> dict[tuple[int, str], KeywordDiscoveryHit]:
    best: dict[tuple[int, str], tuple[datetime, KeywordDiscoveryHit]] = {}
    for hit in hits:
        key = (hit.keyword_id, hit.video_id)
        at = ensure_utc(hit.discovered_at)
        if key not in best or at < best[key][0]:
            best[key] = (at, hit)
    return {key: row for key, (_, row) in best.items()}


def _first_discovery_owner(hits: list[KeywordDiscoveryHit]) -> dict[str, int]:
    best: dict[str, tuple[datetime, int]] = {}
    for hit in hits:
        at = ensure_utc(hit.discovered_at)
        vid = hit.video_id
        kid = hit.keyword_id
        if vid not in best:
            best[vid] = (at, kid)
            continue
        prev_at, prev_kid = best[vid]
        if at < prev_at or (at == prev_at and kid < prev_kid):
            best[vid] = (at, kid)
    return {vid: kid for vid, (_, kid) in best.items()}


def attributed_videos_for_keyword(
    keyword_id: int,
    *,
    mode: AttributionMode,
    hits_for_keyword: list[KeywordDiscoveryHit],
    first_owner: dict[str, int],
) -> set[str]:
    if mode == "all_hits":
        return {h.video_id for h in hits_for_keyword}
    return {vid for vid, owner in first_owner.items() if owner == keyword_id}


def _shared_videos_in_window(hits: list[KeywordDiscoveryHit]) -> set[str]:
    by_video: dict[str, set[int]] = {}
    for hit in hits:
        by_video.setdefault(hit.video_id, set()).add(hit.keyword_id)
    return {vid for vid, kids in by_video.items() if len(kids) > 1}


def load_first_discovery_owner_for_videos(
    session: Session,
    video_ids: set[str],
    *,
    window_from: datetime | None = None,
    window_to: datetime | None = None,
) -> dict[str, int]:
    """Earliest discovery owner per video (scoped to video_ids, optional window)."""
    if not video_ids:
        return {}
    clauses = [
        KeywordDiscoveryHit.video_id.in_(list(video_ids)),
        *_time_clauses(KeywordDiscoveryHit.discovered_at, window_from, window_to),
    ]
    rows = session.execute(
        select(
            KeywordDiscoveryHit.video_id,
            KeywordDiscoveryHit.keyword_id,
            KeywordDiscoveryHit.discovered_at,
        )
        .where(*clauses)
        .order_by(
            KeywordDiscoveryHit.video_id.asc(),
            KeywordDiscoveryHit.discovered_at.asc(),
            KeywordDiscoveryHit.keyword_id.asc(),
        ),
    ).all()
    best: dict[str, tuple[datetime, int]] = {}
    for video_id, keyword_id, discovered_at in rows:
        at = ensure_utc(discovered_at)
        if video_id not in best:
            best[video_id] = (at, int(keyword_id))
            continue
        prev_at, prev_kid = best[video_id]
        if at < prev_at or (at == prev_at and int(keyword_id) < prev_kid):
            best[video_id] = (at, int(keyword_id))
    return {vid: kid for vid, (_, kid) in best.items()}


def load_shared_video_ids_in_window(
    session: Session,
    *,
    window_from: datetime | None = None,
    window_to: datetime | None = None,
) -> set[str]:
    """Videos discovered by more than one keyword in the optional time window."""
    time_clauses = _time_clauses(KeywordDiscoveryHit.discovered_at, window_from, window_to)
    stmt = select(KeywordDiscoveryHit.video_id)
    if time_clauses:
        stmt = stmt.where(*time_clauses)
    rows = session.execute(
        stmt.group_by(KeywordDiscoveryHit.video_id).having(
            func.count(func.distinct(KeywordDiscoveryHit.keyword_id)) > 1,
        ),
    ).all()
    return {row[0] for row in rows}


def _nearest_snapshot_delta_hours(
    baseline: KeywordVideoBaseline,
    snapshots_by_video: dict[str, list[VideoSnapshot]],
) -> float | None:
    """Absolute hours between target horizon and closest snapshot with views (diagnostics only)."""
    target = ensure_utc(baseline.discovery_at) + timedelta(hours=HORIZON_HOURS)
    best: timedelta | None = None
    for snap in snapshots_by_video.get(baseline.video_id, []):
        if snap.views is None:
            continue
        captured = ensure_utc(snap.captured_at)
        delta = abs(captured - target)
        if best is None or delta < best:
            best = delta
    if best is None:
        return None
    return round(best.total_seconds() / 3600.0, 4)


def match_horizon_outcome(
    baseline: KeywordVideoBaseline,
    snapshots_by_video: dict[str, list[VideoSnapshot]],
    *,
    tolerance_hours: float = HORIZON_SNAPSHOT_TOLERANCE_HOURS,
) -> HorizonOutcome | None:
    if baseline.views_at_discovery is None:
        return None
    target = ensure_utc(baseline.discovery_at) + timedelta(hours=HORIZON_HOURS)
    tolerance = timedelta(hours=tolerance_hours)
    candidates = snapshots_by_video.get(baseline.video_id, [])
    best: tuple[timedelta, VideoSnapshot] | None = None
    for snap in candidates:
        if snap.views is None:
            continue
        captured = ensure_utc(snap.captured_at)
        delta = abs(captured - target)
        if delta > tolerance:
            continue
        if best is None or delta < best[0]:
            best = (delta, snap)
    if best is None:
        return None
    snap = best[1]
    captured = ensure_utc(snap.captured_at)
    elapsed = (captured - ensure_utc(baseline.discovery_at)).total_seconds() / 3600.0
    outcome_views = int(snap.views)
    growth = outcome_views - int(baseline.views_at_discovery)
    return HorizonOutcome(
        discovery_at=baseline.discovery_at,
        views_at_discovery=int(baseline.views_at_discovery),
        outcome_views=outcome_views,
        absolute_view_growth=growth,
        actual_elapsed_hours=round(elapsed, 4),
        snapshot_captured_at=captured,
    )


@dataclass(frozen=True, slots=True)
class DelayedOutcomeTally:
    pending: int = 0
    matured: int = 0
    valid: int = 0
    missing: int = 0


def tally_delayed_outcomes_for_videos(
    video_ids: set[str],
    baselines_map: dict[tuple[int, str], KeywordDiscoveryHit],
    keyword_id: int,
    *,
    reference: datetime,
    horizon_hours: int,
    snapshots_by_video: dict[str, list[VideoSnapshot]],
    tolerance_hours: float = HORIZON_SNAPSHOT_TOLERANCE_HOURS,
) -> tuple[DelayedOutcomeTally, list[float]]:
    """Per-keyword 72h counts: pending excluded from missing; matured == valid + missing."""
    horizon_delta = timedelta(hours=horizon_hours)
    reference_utc = ensure_utc(reference)
    tally = DelayedOutcomeTally()
    growths: list[float] = []
    for vid in video_ids:
        base_hit = baselines_map.get((keyword_id, vid))
        if base_hit is None:
            continue
        discovery_at = ensure_utc(base_hit.discovered_at)
        if reference_utc < discovery_at + horizon_delta:
            tally = DelayedOutcomeTally(
                pending=tally.pending + 1,
                matured=tally.matured,
                valid=tally.valid,
                missing=tally.missing,
            )
            continue
        tally = DelayedOutcomeTally(
            pending=tally.pending,
            matured=tally.matured + 1,
            valid=tally.valid,
            missing=tally.missing,
        )
        baseline = KeywordVideoBaseline(
            keyword_id=keyword_id,
            video_id=vid,
            discovery_at=base_hit.discovered_at,
            views_at_discovery=base_hit.views_at_discovery,
            vph_at_discovery=base_hit.vph_at_discovery,
        )
        outcome = match_horizon_outcome(
            baseline,
            snapshots_by_video,
            tolerance_hours=tolerance_hours,
        )
        if outcome is None:
            tally = DelayedOutcomeTally(
                pending=tally.pending,
                matured=tally.matured,
                valid=tally.valid,
                missing=tally.missing + 1,
            )
            continue
        tally = DelayedOutcomeTally(
            pending=tally.pending,
            matured=tally.matured,
            valid=tally.valid + 1,
            missing=tally.missing,
        )
        growths.append(float(outcome.absolute_view_growth))
    return tally, growths


@dataclass(frozen=True, slots=True)
class HorizonCoverageDiagnostics:
    attributed_observation_count: int
    pending_72h_count: int
    matured_72h_count: int
    valid_72h_outcome_count: int
    missing_72h_outcome_count: int
    matured_with_any_snapshot: int
    matured_with_snapshot_in_window: int
    matured_with_only_outside_window: int
    matured_with_no_snapshot: int
    nearest_snapshot_delta_hours: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributed_observation_count": self.attributed_observation_count,
            "pending_72h_count": self.pending_72h_count,
            "matured_72h_count": self.matured_72h_count,
            "valid_72h_outcome_count": self.valid_72h_outcome_count,
            "missing_72h_outcome_count": self.missing_72h_outcome_count,
            "matured_with_any_snapshot": self.matured_with_any_snapshot,
            "matured_with_snapshot_in_window": self.matured_with_snapshot_in_window,
            "matured_with_only_outside_window": self.matured_with_only_outside_window,
            "matured_with_no_snapshot": self.matured_with_no_snapshot,
            "nearest_snapshot_delta_hours": self.nearest_snapshot_delta_hours,
        }


def compute_horizon_coverage_diagnostics(
    session: Session,
    *,
    attribution_mode: AttributionMode = "all_hits",
    now: datetime | None = None,
    keyword_ids: list[int] | None = None,
    horizon_hours: int = HORIZON_HOURS,
    tolerance_hours: float = HORIZON_SNAPSHOT_TOLERANCE_HOURS,
) -> HorizonCoverageDiagnostics:
    """Read-only 72h coverage audit across attributed keyword×video observations."""
    reference = ensure_utc(now or utc_now())
    stmt = select(TargetKeyword.id).order_by(TargetKeyword.id.asc())
    if keyword_ids is not None:
        stmt = stmt.where(TargetKeyword.id.in_(keyword_ids))
    ids = [int(x) for x in session.scalars(stmt).all()]
    if not ids:
        empty_dist: dict[str, Any] = {"n": 0, "note": "INSUFFICIENT_SAMPLE"}
        return HorizonCoverageDiagnostics(0, 0, 0, 0, 0, 0, 0, 0, 0, empty_dist)

    window_hits = list(session.scalars(select(KeywordDiscoveryHit)).all())
    id_set = set(ids)
    hits = [h for h in window_hits if h.keyword_id in id_set]
    first_owner = _first_discovery_owner(window_hits)
    baselines_map = _first_hit_per_keyword_video(hits)
    hits_by_keyword: dict[int, list[KeywordDiscoveryHit]] = {}
    for hit in hits:
        hits_by_keyword.setdefault(hit.keyword_id, []).append(hit)

    observations: list[tuple[int, str, KeywordDiscoveryHit]] = []
    for kid in ids:
        vids = attributed_videos_for_keyword(
            kid,
            mode=attribution_mode,
            hits_for_keyword=hits_by_keyword.get(kid, []),
            first_owner=first_owner,
        )
        for vid in vids:
            base = baselines_map.get((kid, vid))
            if base is not None:
                observations.append((kid, vid, base))

    attributed = len(observations)
    horizon_delta = timedelta(hours=horizon_hours)
    matured_obs: list[tuple[int, str, KeywordDiscoveryHit]] = []
    pending = 0
    for kid, vid, base in observations:
        if reference < ensure_utc(base.discovered_at) + horizon_delta:
            pending += 1
        else:
            matured_obs.append((kid, vid, base))

    matured_video_ids = {vid for _kid, vid, _base in matured_obs}
    all_snaps: dict[str, list[VideoSnapshot]] = {}
    if matured_video_ids:
        all_snaps = load_snapshots_for_horizon(session, matured_video_ids)

    any_snap = in_window = outside_only = no_snap = 0
    nearest_deltas: list[float] = []
    valid = 0
    missing = 0
    tolerance = timedelta(hours=tolerance_hours)

    for _kid, vid, base in matured_obs:
        baseline = KeywordVideoBaseline(
            keyword_id=_kid,
            video_id=vid,
            discovery_at=base.discovered_at,
            views_at_discovery=base.views_at_discovery,
            vph_at_discovery=base.vph_at_discovery,
        )
        outcome = match_horizon_outcome(baseline, all_snaps, tolerance_hours=tolerance_hours)
        if outcome is not None:
            valid += 1
        else:
            missing += 1

        snaps = [s for s in all_snaps.get(vid, []) if s.views is not None]
        if not snaps:
            no_snap += 1
            continue
        any_snap += 1
        target = ensure_utc(base.discovered_at) + horizon_delta
        has_in = any(abs(ensure_utc(s.captured_at) - target) <= tolerance for s in snaps)
        if has_in:
            in_window += 1
        else:
            outside_only += 1
        delta_h = _nearest_snapshot_delta_hours(baseline, all_snaps)
        if delta_h is not None:
            nearest_deltas.append(delta_h)

    dist: dict[str, Any]
    if nearest_deltas:
        ordered = sorted(nearest_deltas)
        dist = {
            "n": len(ordered),
            "p50": _median(nearest_deltas),
            "p75": round(_percentile(ordered, 75), 4),
            "p90": round(_percentile(ordered, 90), 4),
        }
    else:
        dist = {"n": 0, "note": "INSUFFICIENT_SAMPLE"}

    return HorizonCoverageDiagnostics(
        attributed_observation_count=attributed,
        pending_72h_count=pending,
        matured_72h_count=len(matured_obs),
        valid_72h_outcome_count=valid,
        missing_72h_outcome_count=missing,
        matured_with_any_snapshot=any_snap,
        matured_with_snapshot_in_window=in_window,
        matured_with_only_outside_window=outside_only,
        matured_with_no_snapshot=no_snap,
        nearest_snapshot_delta_hours=dist,
    )


def derive_evidence_status(detail: EvidenceDetail) -> str:
    if detail.unique_video_count < 1 or detail.scan_count < 1:
        return "insufficient"
    if detail.observed_72h_video_count < 1:
        return "early"
    return "established"


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 4)
    return round((ordered[mid - 1] + ordered[mid]) / 2.0, 4)


@dataclass
class KeywordBatchAggregates:
    keyword_id: int
    keyword: str
    scan_count: int = 0
    first_scan_at: datetime | None = None
    last_scan_at: datetime | None = None
    discovery_hit_count: int = 0
    unique_video_count: int = 0
    unique_channel_count: int = 0
    within_keyword_duplicate_hit_count: int = 0
    cross_keyword_duplicate_count: int = 0
    already_known_video_count: int = 0
    duplicate_hit_count: int = 0
    duplicate_rate: float | None = None
    regular_video_count: int = 0
    short_count: int = 0
    live_count: int = 0
    qualification_passed_count: int = 0
    qualification_rejected_count: int = 0
    qualification_pass_rate: float | None = None
    persisted_for_monitoring_count: int = 0
    monitored_video_count: int = 0
    new_to_corpus_video_count: int = 0
    shared_video_count: int = 0
    exclusive_first_discovery_count: int = 0
    attributed_video_count: int = 0
    videos_with_snapshot_count: int = 0
    videos_with_snapshot_24h_count: int = 0
    videos_with_snapshot_48h_count: int = 0
    videos_with_snapshot_72h_count: int = 0
    monitorable_video_count: int = 0
    breakout_eligible_video_count: int = 0
    breakout_ranked_video_count: int = 0
    top_decile_breakout_count: int = 0
    top_decile_breakout_rate: float | None = None
    discovery_vph_observation_count: int = 0
    median_vph_at_discovery: float | None = None
    p90_vph_at_discovery: float | None = None
    median_current_vph: float | None = None
    observed_72h_video_count: int = 0
    missing_72h_video_count: int = 0
    matured_72h_video_count: int = 0
    pending_72h_video_count: int = 0
    median_absolute_view_growth_72h: float | None = None
    p90_absolute_view_growth_72h: float | None = None
    evidence_status: str = "insufficient"
    evidence_detail: EvidenceDetail = field(default_factory=lambda: EvidenceDetail(0, 0, 0, 0))
    current_tier_a_count: int | None = None
    current_tier_b_count: int | None = None
    current_tier_c_count: int | None = None


def _horizon_capture_window(
    baselines: list[KeywordVideoBaseline],
    *,
    horizon_hours: int = HORIZON_HOURS,
    tolerance_hours: float = HORIZON_SNAPSHOT_TOLERANCE_HOURS,
) -> tuple[datetime, datetime] | None:
    discovery_times = [
        ensure_utc(b.discovery_at)
        for b in baselines
        if b.views_at_discovery is not None
    ]
    if not discovery_times:
        return None
    earliest = min(discovery_times)
    latest = max(discovery_times)
    return (
        earliest + timedelta(hours=horizon_hours - tolerance_hours),
        latest + timedelta(hours=horizon_hours + tolerance_hours),
    )


def horizon_snapshots_exist_in_window(
    session: Session,
    video_ids: set[str],
    *,
    captured_from: datetime,
    captured_to: datetime,
) -> bool:
    if not video_ids:
        return False
    probe = (
        select(VideoSnapshot.video_id)
        .where(
            VideoSnapshot.video_id.in_(list(video_ids)),
            VideoSnapshot.captured_at >= ensure_utc(captured_from),
            VideoSnapshot.captured_at <= ensure_utc(captured_to),
            VideoSnapshot.views.is_not(None),
        )
        .limit(1)
    )
    return session.scalars(probe).first() is not None


def load_snapshots_for_horizon(
    session: Session,
    video_ids: set[str],
    *,
    captured_from: datetime | None = None,
    captured_to: datetime | None = None,
) -> dict[str, list[VideoSnapshot]]:
    if not video_ids:
        return {}
    stmt = select(VideoSnapshot).where(VideoSnapshot.video_id.in_(list(video_ids)))
    if captured_from is not None:
        stmt = stmt.where(VideoSnapshot.captured_at >= ensure_utc(captured_from))
    if captured_to is not None:
        stmt = stmt.where(VideoSnapshot.captured_at <= ensure_utc(captured_to))
    stmt = stmt.order_by(VideoSnapshot.video_id.asc(), VideoSnapshot.captured_at.asc())
    grouped: dict[str, list[VideoSnapshot]] = {}
    for row in session.scalars(stmt).all():
        grouped.setdefault(row.video_id, []).append(row)
    return grouped


def _snapshot_coverage_from_max_age(rows: list[tuple[str, float | None]]) -> tuple[int, int, int, int]:
    any_snap = len(rows)
    at_24 = sum(1 for _vid, age in rows if age is not None and age >= 24.0)
    at_48 = sum(1 for _vid, age in rows if age is not None and age >= 48.0)
    at_72 = sum(1 for _vid, age in rows if age is not None and age >= 72.0)
    return any_snap, at_24, at_48, at_72


def evaluate_keywords_batch(
    session: Session,
    keyword_records: list[TargetKeyword],
    *,
    context: KeywordEvaluationContext,
    breakout_map: dict[str, VideoBreakoutInfo],
    include_current_tiers: bool = False,
    options: KeywordEvaluationOptions | None = None,
    monitoring_states_by_id: dict[str, MonitoredVideoState] | None = None,
) -> dict[int, KeywordBatchAggregates]:
    opts = options or KeywordEvaluationOptions()
    if not keyword_records:
        return {}

    keyword_ids = [k.id for k in keyword_records]
    id_to_keyword = {k.id: k.keyword for k in keyword_records}

    scan_filters = [
        KeywordScanRun.keyword_id.in_(keyword_ids),
        *_time_clauses(KeywordScanRun.started_at, context.window_from, context.window_to),
    ]
    scan_rows = session.execute(
        select(
            KeywordScanRun.keyword_id,
            func.count(),
            func.min(KeywordScanRun.started_at),
            func.max(KeywordScanRun.started_at),
        )
        .where(*scan_filters)
        .group_by(KeywordScanRun.keyword_id),
    ).all()
    scan_by_id = {
        int(kid): (int(cnt), first, last) for kid, cnt, first, last in scan_rows
    }

    hit_filters = [
        KeywordDiscoveryHit.keyword_id.in_(keyword_ids),
        *_time_clauses(KeywordDiscoveryHit.discovered_at, context.window_from, context.window_to),
    ]
    all_hits = list(session.scalars(select(KeywordDiscoveryHit).where(*hit_filters)).all())
    attributed_video_ids_early: set[str] = {hit.video_id for hit in all_hits}
    if context.attribution_mode == "first_discovery":
        first_owner = load_first_discovery_owner_for_videos(
            session,
            attributed_video_ids_early,
            window_from=context.window_from,
            window_to=context.window_to,
        )
    else:
        first_owner = {}
    shared_videos = load_shared_video_ids_in_window(
        session,
        window_from=context.window_from,
        window_to=context.window_to,
    )
    baselines_map = _first_hit_per_keyword_video(all_hits)

    hits_by_keyword: dict[int, list[KeywordDiscoveryHit]] = {}
    for hit in all_hits:
        hits_by_keyword.setdefault(hit.keyword_id, []).append(hit)

    attributed_video_ids: set[str] = set()
    per_keyword_videos: dict[int, set[str]] = {}
    for kid in keyword_ids:
        vids = attributed_videos_for_keyword(
            kid,
            mode=context.attribution_mode,
            hits_for_keyword=hits_by_keyword.get(kid, []),
            first_owner=first_owner,
        )
        per_keyword_videos[kid] = vids
        attributed_video_ids |= vids

    snapshots_by_video: dict[str, list[VideoSnapshot]] = {}
    horizon_snapshot_rows_loaded = 0
    if opts.include_delayed and attributed_video_ids:
        baselines_for_window = [
            KeywordVideoBaseline(
                keyword_id=kid,
                video_id=vid,
                discovery_at=baselines_map[(kid, vid)].discovered_at,
                views_at_discovery=baselines_map[(kid, vid)].views_at_discovery,
                vph_at_discovery=baselines_map[(kid, vid)].vph_at_discovery,
            )
            for kid in keyword_ids
            for vid in per_keyword_videos.get(kid, set())
            if (kid, vid) in baselines_map
        ]
        capture_window = _horizon_capture_window(
            baselines_for_window,
            horizon_hours=context.horizon_hours,
            tolerance_hours=context.horizon_snapshot_tolerance_hours,
        )
        if capture_window is not None and horizon_snapshots_exist_in_window(
            session,
            attributed_video_ids,
            captured_from=capture_window[0],
            captured_to=capture_window[1],
        ):
            snapshots_by_video = load_snapshots_for_horizon(
                session,
                attributed_video_ids,
                captured_from=capture_window[0],
                captured_to=capture_window[1],
            )
            horizon_snapshot_rows_loaded = sum(len(rows) for rows in snapshots_by_video.values())

    monitored_ids: dict[int, set[str]] = {}
    for kid in keyword_ids:
        persisted = {
            h.video_id
            for h in hits_by_keyword.get(kid, [])
            if h.persisted_for_monitoring
        }
        monitored_ids[kid] = persisted

    all_monitored = set().union(*monitored_ids.values()) if monitored_ids else set()
    snap_coverage_rows: list[tuple[str, float | None]] = []
    if all_monitored:
        snap_coverage_rows = list(
            session.execute(
                select(
                    VideoSnapshot.video_id,
                    func.max(VideoSnapshot.age_hours),
                )
                .where(VideoSnapshot.video_id.in_(all_monitored))
                .group_by(VideoSnapshot.video_id),
            ).all(),
        )
    snap_by_vid = {vid: age for vid, age in snap_coverage_rows}

    tier_by_video: dict[str, MonitoringTier] | None = None
    if include_current_tiers and attributed_video_ids:
        if monitoring_states_by_id is not None:
            states = [
                monitoring_states_by_id[vid]
                for vid in attributed_video_ids
                if vid in monitoring_states_by_id
            ]
        else:
            from app.services.monitoring_video_source import load_monitored_video_states

            states = [
                s
                for s in load_monitored_video_states(session, now=context.evaluated_at)
                if s.video_id in attributed_video_ids
            ]
        from app.services.monitoring_tier_budget_policy import TierCandidateInput

        inputs = [
            TierCandidateInput(
                video_id=s.video_id,
                channel_id=s.channel_id,
                raw_vph=s.raw_vph,
                age_hours=s.age_hours,
                baseline_status=s.channel_velocity_baseline_status,
                vph_vs_channel_median=s.vph_vs_channel_median,
            )
            for s in states
        ]
        tier_by_video = {d.video_id: d.tier for d in assign_monitoring_tiers(inputs)}

    results: dict[int, KeywordBatchAggregates] = {}
    cutoff = context.top_decile_rank_cutoff

    for kid in keyword_ids:
        hits = hits_by_keyword.get(kid, [])
        scan = scan_by_id.get(kid, (0, None, None))
        agg = KeywordBatchAggregates(keyword_id=kid, keyword=id_to_keyword[kid])
        agg.scan_count = scan[0]
        agg.first_scan_at = scan[1]
        agg.last_scan_at = scan[2]

        agg.discovery_hit_count = len(hits)
        raw_unique_videos = {h.video_id for h in hits}
        agg.unique_video_count = len(raw_unique_videos)
        attr_vids = per_keyword_videos.get(kid, set())
        agg.attributed_video_count = len(attr_vids)

        channels = {
            h.channel_id for h in hits if h.channel_id and str(h.channel_id).strip()
        }
        agg.unique_channel_count = len(channels)
        agg.within_keyword_duplicate_hit_count = sum(1 for h in hits if h.was_within_keyword_duplicate)
        agg.cross_keyword_duplicate_count = sum(1 for h in hits if h.was_cross_keyword_duplicate)
        agg.already_known_video_count = sum(1 for h in hits if h.video_existed_before_discovery)
        agg.duplicate_hit_count = agg.within_keyword_duplicate_hit_count + agg.cross_keyword_duplicate_count
        agg.duplicate_rate = (
            round(agg.duplicate_hit_count / agg.discovery_hit_count, 4) if agg.discovery_hit_count else None
        )
        agg.regular_video_count = sum(1 for h in hits if h.content_format == "regular")
        agg.short_count = sum(1 for h in hits if h.content_format == "short")
        agg.live_count = sum(1 for h in hits if h.content_format == "live")
        agg.qualification_passed_count = sum(1 for h in hits if h.qualification_state == "passed")
        agg.qualification_rejected_count = sum(1 for h in hits if h.qualification_state == "rejected")
        qual_total = agg.qualification_passed_count + agg.qualification_rejected_count
        agg.qualification_pass_rate = round(agg.qualification_passed_count / qual_total, 4) if qual_total else None
        agg.persisted_for_monitoring_count = sum(1 for h in hits if h.persisted_for_monitoring)
        agg.monitored_video_count = len(monitored_ids.get(kid, set()))
        agg.new_to_corpus_video_count = sum(1 for h in hits if not h.video_existed_before_discovery)

        agg.shared_video_count = sum(1 for vid in attr_vids if vid in shared_videos)
        agg.exclusive_first_discovery_count = sum(
            1 for vid in attr_vids if first_owner.get(vid) == kid and vid not in shared_videos
        )

        mon = monitored_ids.get(kid, set())
        if mon:
            rows = [(vid, snap_by_vid.get(vid)) for vid in mon if vid in snap_by_vid]
            agg.videos_with_snapshot_count, agg.videos_with_snapshot_24h_count, agg.videos_with_snapshot_48h_count, agg.videos_with_snapshot_72h_count = _snapshot_coverage_from_max_age(rows)

        discovery_vphs: list[float] = []
        current_vphs: list[float] = []
        for vid in attr_vids:
            base = baselines_map.get((kid, vid))
            if base and base.vph_at_discovery is not None:
                discovery_vphs.append(float(base.vph_at_discovery))
            if opts.include_breakout:
                info = breakout_map.get(vid)
                if info and info.current_vph is not None:
                    current_vphs.append(float(info.current_vph))
                if info and info.eligible:
                    agg.breakout_eligible_video_count += 1
                if info and info.rank is not None:
                    agg.breakout_ranked_video_count += 1
                    if info.rank <= cutoff:
                        agg.top_decile_breakout_count += 1
                if vid in breakout_map:
                    agg.monitorable_video_count += 1

        if opts.include_breakout and agg.breakout_ranked_video_count:
            agg.top_decile_breakout_rate = round(
                agg.top_decile_breakout_count / agg.breakout_ranked_video_count,
                4,
            )

        agg.discovery_vph_observation_count = len(discovery_vphs)
        if discovery_vphs:
            ordered = sorted(discovery_vphs)
            agg.median_vph_at_discovery = _median(discovery_vphs)
            agg.p90_vph_at_discovery = round(_percentile(ordered, 90), 4)
        if opts.include_breakout:
            agg.median_current_vph = _median(current_vphs)

        growths: list[float] = []
        if opts.include_delayed:
            tally, growths = tally_delayed_outcomes_for_videos(
                attr_vids,
                baselines_map,
                kid,
                reference=context.evaluated_at,
                horizon_hours=context.horizon_hours,
                snapshots_by_video=snapshots_by_video,
                tolerance_hours=context.horizon_snapshot_tolerance_hours,
            )
            agg.pending_72h_video_count = tally.pending
            agg.matured_72h_video_count = tally.matured
            agg.observed_72h_video_count = tally.valid
            agg.missing_72h_video_count = tally.missing
            agg.median_absolute_view_growth_72h = _median(growths)
            if growths:
                ordered_growths = sorted(growths)
                agg.p90_absolute_view_growth_72h = round(_percentile(ordered_growths, 90), 4)
        else:
            agg.pending_72h_video_count = 0
            agg.missing_72h_video_count = 0
            agg.matured_72h_video_count = 0
            agg.median_absolute_view_growth_72h = None
            agg.p90_absolute_view_growth_72h = None

        agg.evidence_detail = EvidenceDetail(
            scan_count=agg.scan_count,
            unique_video_count=agg.unique_video_count,
            breakout_eligible_video_count=agg.breakout_eligible_video_count,
            observed_72h_video_count=agg.observed_72h_video_count,
        )
        agg.evidence_status = derive_evidence_status(agg.evidence_detail)

        if tier_by_video is not None:
            a = b = c = 0
            for vid in attr_vids:
                tier = tier_by_video.get(vid)
                if tier == MonitoringTier.A:
                    a += 1
                elif tier == MonitoringTier.B:
                    b += 1
                elif tier == MonitoringTier.C:
                    c += 1
            agg.current_tier_a_count = a
            agg.current_tier_b_count = b
            agg.current_tier_c_count = c

        results[kid] = agg

    return results


def make_evaluation_context(
    *,
    global_eligible_video_count: int,
    attribution_mode: AttributionMode = "all_hits",
    window_from: datetime | None = None,
    window_to: datetime | None = None,
    evaluated_at: datetime | None = None,
) -> KeywordEvaluationContext:
    reference = evaluated_at or utc_now()
    global_n = global_eligible_video_count
    cutoff = max(1, int(math.ceil(global_n * 0.10))) if global_n else 0
    return KeywordEvaluationContext(
        evaluated_at=reference,
        attribution_mode=attribution_mode,
        window_from=window_from,
        window_to=window_to,
        ranking_version=BREAKOUT_RANK_VERSION,
        global_eligible_video_count=global_n,
        horizon_hours=HORIZON_HOURS,
        horizon_snapshot_tolerance_hours=HORIZON_SNAPSHOT_TOLERANCE_HOURS,
        top_decile_rank_cutoff=cutoff,
    )
