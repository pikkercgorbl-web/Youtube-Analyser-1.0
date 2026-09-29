"""Read-only keyword performance metrics API (Stage 1.16A / 1.18B)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.schemas import (
    KeywordPerformanceEvidenceDetailResponse,
    KeywordPerformanceListResponse,
    KeywordPerformanceMetricsResponse,
)
from app.services.keyword_performance_evaluation import AttributionMode
from app.services.keyword_performance_service import (
    KeywordPerformanceMetrics,
    get_keyword_performance,
    list_keyword_performance,
)

router = APIRouter()

_VALID_ATTRIBUTION = {"all_hits", "first_discovery"}


def _to_response(metrics: KeywordPerformanceMetrics) -> KeywordPerformanceMetricsResponse:
    evidence = None
    if metrics.evidence_detail is not None:
        evidence = KeywordPerformanceEvidenceDetailResponse(
            scan_count=metrics.evidence_detail.scan_count,
            unique_video_count=metrics.evidence_detail.unique_video_count,
            breakout_eligible_video_count=metrics.evidence_detail.breakout_eligible_video_count,
            observed_72h_video_count=metrics.evidence_detail.observed_72h_video_count,
        )
    return KeywordPerformanceMetricsResponse(
        keyword_id=metrics.keyword_id,
        keyword=metrics.keyword,
        scan_count=metrics.scan_count,
        first_scan_at=metrics.first_scan_at,
        last_scan_at=metrics.last_scan_at,
        discovery_hit_count=metrics.discovery_hit_count,
        unique_video_count=metrics.unique_video_count,
        unique_channel_count=metrics.unique_channel_count,
        within_keyword_duplicate_hit_count=metrics.within_keyword_duplicate_hit_count,
        cross_keyword_duplicate_count=metrics.cross_keyword_duplicate_count,
        already_known_video_count=metrics.already_known_video_count,
        duplicate_hit_count=metrics.duplicate_hit_count,
        duplicate_rate=metrics.duplicate_rate,
        regular_video_count=metrics.regular_video_count,
        short_count=metrics.short_count,
        live_count=metrics.live_count,
        qualification_passed_count=metrics.qualification_passed_count,
        qualification_rejected_count=metrics.qualification_rejected_count,
        qualification_pass_rate=metrics.qualification_pass_rate,
        persisted_for_monitoring_count=metrics.persisted_for_monitoring_count,
        monitored_video_count=metrics.monitored_video_count,
        videos_with_snapshot_count=metrics.videos_with_snapshot_count,
        videos_with_snapshot_24h_count=metrics.videos_with_snapshot_24h_count,
        videos_with_snapshot_48h_count=metrics.videos_with_snapshot_48h_count,
        videos_with_snapshot_72h_count=metrics.videos_with_snapshot_72h_count,
        current_tier_a_count=metrics.current_tier_a_count,
        current_tier_b_count=metrics.current_tier_b_count,
        current_tier_c_count=metrics.current_tier_c_count,
        t24_outcome_count=metrics.t24_outcome_count,
        t48_outcome_count=metrics.t48_outcome_count,
        t72_outcome_count=metrics.t72_outcome_count,
        confirmed_breakout_count=metrics.confirmed_breakout_count,
        videos_per_scan=metrics.videos_per_scan,
        unique_videos_per_scan=metrics.unique_videos_per_scan,
        unique_channels_per_scan=metrics.unique_channels_per_scan,
        persisted_videos_per_scan=metrics.persisted_videos_per_scan,
        qualification_passed_per_scan=metrics.qualification_passed_per_scan,
        lifecycle_status=metrics.lifecycle_status,
        source_type=metrics.source_type,
        last_checked=metrics.last_checked,
        next_scan_at=metrics.next_scan_at,
        scan_interval_seconds=metrics.scan_interval_seconds,
        is_due=metrics.is_due,
        overdue_seconds=metrics.overdue_seconds,
        scheduling_hint=metrics.scheduling_hint,
        evaluated_at=metrics.evaluated_at,
        attribution_mode=metrics.attribution_mode,
        window_from=metrics.window_from,
        window_to=metrics.window_to,
        ranking_version=metrics.ranking_version,
        global_eligible_video_count=metrics.global_eligible_video_count,
        horizon_hours=metrics.horizon_hours,
        horizon_snapshot_tolerance_hours=metrics.horizon_snapshot_tolerance_hours,
        new_to_corpus_video_count=metrics.new_to_corpus_video_count,
        shared_video_count=metrics.shared_video_count,
        exclusive_first_discovery_count=metrics.exclusive_first_discovery_count,
        attributed_video_count=metrics.attributed_video_count,
        monitorable_video_count=metrics.monitorable_video_count,
        breakout_eligible_video_count=metrics.breakout_eligible_video_count,
        breakout_ranked_video_count=metrics.breakout_ranked_video_count,
        top_decile_breakout_count=metrics.top_decile_breakout_count,
        top_decile_breakout_rate=metrics.top_decile_breakout_rate,
        median_vph_at_discovery=metrics.median_vph_at_discovery,
        p90_vph_at_discovery=metrics.p90_vph_at_discovery,
        median_current_vph=metrics.median_current_vph,
        observed_72h_video_count=metrics.observed_72h_video_count,
        missing_72h_video_count=metrics.missing_72h_video_count,
        median_absolute_view_growth_72h=metrics.median_absolute_view_growth_72h,
        evidence_status=metrics.evidence_status,
        evidence_detail=evidence,
    )


@router.get("/performance", response_model=KeywordPerformanceListResponse)
def list_keywords_performance(
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    from_timestamp: datetime | None = Query(None),
    to_timestamp: datetime | None = Query(None),
    include_current_tiers: bool = Query(False),
    include_breakout: bool = Query(True),
    include_delayed: bool = Query(True),
    attribution_mode: str = Query("all_hits"),
) -> KeywordPerformanceListResponse:
    mode: AttributionMode = "all_hits"
    if attribution_mode not in _VALID_ATTRIBUTION:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid attribution_mode")
    mode = attribution_mode  # type: ignore[assignment]

    result = list_keyword_performance(
        db,
        limit=limit,
        from_timestamp=from_timestamp,
        to_timestamp=to_timestamp,
        include_current_tiers=include_current_tiers,
        include_breakout=include_breakout,
        include_delayed=include_delayed,
        attribution_mode=mode,
    )
    ctx = result.context
    return KeywordPerformanceListResponse(
        items=[_to_response(item) for item in result.items],
        limit=limit,
        evaluated_at=ctx.evaluated_at,
        attribution_mode=ctx.attribution_mode,
        window_from=ctx.window_from,
        window_to=ctx.window_to,
        ranking_version=ctx.ranking_version,
        global_eligible_video_count=ctx.global_eligible_video_count,
        horizon_hours=ctx.horizon_hours,
        horizon_snapshot_tolerance_hours=ctx.horizon_snapshot_tolerance_hours,
    )


@router.get("/{keyword_id}/performance", response_model=KeywordPerformanceMetricsResponse)
def get_keyword_performance_by_id(
    keyword_id: int,
    db: Session = Depends(get_db),
    from_timestamp: datetime | None = Query(None),
    to_timestamp: datetime | None = Query(None),
    include_current_tiers: bool = Query(False),
    include_breakout: bool = Query(True),
    include_delayed: bool = Query(True),
    attribution_mode: str = Query("all_hits"),
) -> KeywordPerformanceMetricsResponse:
    if attribution_mode not in _VALID_ATTRIBUTION:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid attribution_mode")
    metrics = get_keyword_performance(
        db,
        keyword_id,
        from_timestamp=from_timestamp,
        to_timestamp=to_timestamp,
        include_current_tiers=include_current_tiers,
        include_breakout=include_breakout,
        include_delayed=include_delayed,
        attribution_mode=attribution_mode,  # type: ignore[arg-type]
    )
    if metrics is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Keyword not found")
    return _to_response(metrics)
