"""Read-only keyword lifecycle evidence API (Stage 1.20B)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.schemas import (
    BreakoutEvidenceResponse,
    DelayedOutcomeEvidenceResponse,
    DiscoveryEvidenceResponse,
    DiscoveryVphEvidenceResponse,
    EvidenceFamilyMetaResponse,
    KeywordEvidenceListResponse,
    KeywordEvidenceResponse,
    LifecycleContextEvidenceResponse,
    RedundancyEvidenceResponse,
    ScanEvidenceResponse,
    SchedulingEvidenceResponse,
)
from app.services.keyword_evidence_service import get_keyword_evidence, list_keyword_evidence
from app.services.keyword_evidence_types import KeywordEvidence
from app.services.keyword_performance_evaluation import AttributionMode

router = APIRouter()

_VALID_ATTRIBUTION = {"all_hits", "first_discovery"}


def _meta_response(meta) -> EvidenceFamilyMetaResponse:
    return EvidenceFamilyMetaResponse(availability=meta.availability, role=meta.role)


def _to_response(item: KeywordEvidence) -> KeywordEvidenceResponse:
    return KeywordEvidenceResponse(
        keyword_id=item.keyword_id,
        keyword=item.keyword,
        lifecycle_status=item.lifecycle_status,
        source_type=item.source_type,
        parent_keyword_id=item.parent_keyword_id,
        scan=ScanEvidenceResponse(
            meta=_meta_response(item.scan.meta),
            total_scan_count=item.scan.total_scan_count,
            successful_scan_count=item.scan.successful_scan_count,
            failed_scan_count=item.scan.failed_scan_count,
            latest_scan_at=item.scan.latest_scan_at,
            latest_scan_status=item.scan.latest_scan_status,
            total_raw_candidates=item.scan.total_raw_candidates,
            total_unique_candidates=item.scan.total_unique_candidates,
            total_persisted_videos=item.scan.total_persisted_videos,
        ),
        discovery=DiscoveryEvidenceResponse(
            meta=_meta_response(item.discovery.meta),
            total_discovery_hits=item.discovery.total_discovery_hits,
            unique_discovered_video_count=item.discovery.unique_discovered_video_count,
            new_to_database_video_count=item.discovery.new_to_database_video_count,
            persisted_for_monitoring_count=item.discovery.persisted_for_monitoring_count,
            attributed_observation_count=item.discovery.attributed_observation_count,
            unique_candidate_rate=item.discovery.unique_candidate_rate,
            persistence_rate=item.discovery.persistence_rate,
            new_video_rate=item.discovery.new_video_rate,
        ),
        redundancy=RedundancyEvidenceResponse(
            meta=_meta_response(item.redundancy.meta),
            within_keyword_duplicate_count=item.redundancy.within_keyword_duplicate_count,
            cross_keyword_duplicate_count=item.redundancy.cross_keyword_duplicate_count,
            duplicate_hit_count=item.redundancy.duplicate_hit_count,
            duplicate_rate=item.redundancy.duplicate_rate,
            unique_yield_rate=item.redundancy.unique_yield_rate,
        ),
        discovery_vph=DiscoveryVphEvidenceResponse(
            meta=_meta_response(item.discovery_vph.meta),
            observation_count=item.discovery_vph.observation_count,
            median_discovery_vph=item.discovery_vph.median_discovery_vph,
            p90_discovery_vph=item.discovery_vph.p90_discovery_vph,
        ),
        breakout=BreakoutEvidenceResponse(
            meta=_meta_response(item.breakout.meta),
            breakout_eligible_count=item.breakout.breakout_eligible_count,
            top_decile_breakout_count=item.breakout.top_decile_breakout_count,
            top_decile_breakout_rate=item.breakout.top_decile_breakout_rate,
            ranking_version=item.breakout.ranking_version,
            global_eligible_video_count=item.breakout.global_eligible_video_count,
        ),
        delayed_outcome=DelayedOutcomeEvidenceResponse(
            meta=_meta_response(item.delayed_outcome.meta),
            attributed_observation_count=item.delayed_outcome.attributed_observation_count,
            matured_72h_count=item.delayed_outcome.matured_72h_count,
            valid_72h_outcome_count=item.delayed_outcome.valid_72h_outcome_count,
            missing_72h_outcome_count=item.delayed_outcome.missing_72h_outcome_count,
            median_72h_growth=item.delayed_outcome.median_72h_growth,
            p90_72h_growth=item.delayed_outcome.p90_72h_growth,
            horizon_hours=item.delayed_outcome.horizon_hours,
            horizon_snapshot_tolerance_hours=item.delayed_outcome.horizon_snapshot_tolerance_hours,
        ),
        lifecycle_context=LifecycleContextEvidenceResponse(
            meta=_meta_response(item.lifecycle_context.meta),
            status_changed_at=item.lifecycle_context.status_changed_at,
            status_reason=item.lifecycle_context.status_reason,
            last_manual_change_at=item.lifecycle_context.last_manual_change_at,
            latest_lifecycle_actor_source=item.lifecycle_context.latest_lifecycle_actor_source,
        ),
        scheduling=SchedulingEvidenceResponse(
            meta=_meta_response(item.scheduling.meta),
            last_checked=item.scheduling.last_checked,
            next_scan_at=item.scheduling.next_scan_at,
            scan_interval_seconds=item.scheduling.scan_interval_seconds,
            is_due=item.scheduling.is_due,
            scheduling_hint=item.scheduling.scheduling_hint,
        ),
        attribution_mode=item.attribution_mode,
        evaluated_at=item.evaluated_at,
        include_breakout=item.include_breakout,
        include_delayed=item.include_delayed,
    )


@router.get("/evidence", response_model=KeywordEvidenceListResponse)
def list_keywords_evidence(
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    lifecycle_status: str | None = Query(None),
    attribution_mode: str = Query("all_hits"),
    include_breakout: bool = Query(False),
    include_delayed: bool = Query(False),
) -> KeywordEvidenceListResponse:
    if attribution_mode not in _VALID_ATTRIBUTION:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid attribution_mode")
    mode: AttributionMode = attribution_mode  # type: ignore[assignment]
    result = list_keyword_evidence(
        db,
        limit=limit,
        lifecycle_status=lifecycle_status,
        attribution_mode=mode,
        include_breakout=include_breakout,
        include_delayed=include_delayed,
    )
    return KeywordEvidenceListResponse(
        evaluated_at=result.evaluated_at,
        attribution_mode=result.attribution_mode,
        include_breakout=result.include_breakout,
        include_delayed=result.include_delayed,
        ranking_version=result.ranking_version,
        global_eligible_video_count=result.global_eligible_video_count,
        limit=limit,
        items=[_to_response(item) for item in result.items],
    )


@router.get("/{keyword_id}/evidence", response_model=KeywordEvidenceResponse)
def get_keyword_evidence_by_id(
    keyword_id: int,
    db: Session = Depends(get_db),
    attribution_mode: str = Query("all_hits"),
    include_breakout: bool = Query(True),
    include_delayed: bool = Query(True),
) -> KeywordEvidenceResponse:
    if attribution_mode not in _VALID_ATTRIBUTION:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid attribution_mode")
    item = get_keyword_evidence(
        db,
        keyword_id,
        attribution_mode=attribution_mode,  # type: ignore[arg-type]
        include_breakout=include_breakout,
        include_delayed=include_delayed,
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Keyword not found")
    return _to_response(item)
