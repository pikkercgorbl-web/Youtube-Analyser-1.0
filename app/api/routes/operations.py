"""Operations overview API (Stage 1.19B)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.schemas import (
    DiscoveryCycleOpsResponse,
    DiscoveryOperationsBlockResponse,
    KeywordOutcomeOperationsBlockResponse,
    MonitoringCycleHistoryItemResponse,
    MonitoringOperationsBlockResponse,
    OperationsErrorsBlockResponse,
    OperationsOverviewResponse,
    RecentCyclesBlockResponse,
    SnapshotDailyCountResponse,
    SnapshotOperationsBlockResponse,
    WorkerActivityResponse,
)
from app.services.operations_overview_service import (
    DiscoveryCycleSummaryOps,
    OperationsOverview,
    WorkerActivityBlock,
    build_operations_overview,
)

router = APIRouter()


def _worker_response(block: WorkerActivityBlock) -> WorkerActivityResponse:
    return WorkerActivityResponse(**asdict(block))


def _discovery_cycle_response(row: DiscoveryCycleSummaryOps) -> DiscoveryCycleOpsResponse:
    return DiscoveryCycleOpsResponse(
        discovery_run_id=row.discovery_run_id,
        started_at=row.started_at,
        finished_at=row.finished_at,
        runtime_seconds=row.runtime_seconds,
        keywords_scanned=row.keywords_scanned,
        raw_candidates=row.raw_candidates,
        unique_candidates=row.unique_candidates,
        persisted_videos=row.persisted_videos,
        qualification_passed=row.qualification_passed,
        qualification_rejected=row.qualification_rejected,
        keyword_scan_failures=row.keyword_scan_failures,
        error_summaries=list(row.error_summaries),
    )


def _to_response(overview: OperationsOverview) -> OperationsOverviewResponse:
    d = overview.discovery
    m = overview.monitoring
    return OperationsOverviewResponse(
        generated_at=overview.generated_at,
        discovery=DiscoveryOperationsBlockResponse(
            worker=_worker_response(d.worker),
            last_cycle_started_at=d.last_cycle_started_at,
            last_cycle_finished_at=d.last_cycle_finished_at,
            last_cycle_status=d.last_cycle_status,
            last_run_id=d.last_run_id,
            last_error=d.last_error,
            last_cycle_runtime_seconds=d.last_cycle_runtime_seconds,
            keywords_scanned_last_cycle=d.keywords_scanned_last_cycle,
            raw_candidates_last_cycle=d.raw_candidates_last_cycle,
            unique_videos_last_cycle=d.unique_videos_last_cycle,
            persisted_videos_last_cycle=d.persisted_videos_last_cycle,
            keyword_errors_last_cycle=d.keyword_errors_last_cycle,
            keywords_due_now=d.keywords_due_now,
            keywords_due_next_1h=d.keywords_due_next_1h,
            keywords_due_next_24h=d.keywords_due_next_24h,
            keywords_due_next_24h_includes_1h=d.keywords_due_next_24h_includes_1h,
        ),
        monitoring=MonitoringOperationsBlockResponse(
            worker=_worker_response(m.worker),
            last_cycle_started_at=m.last_cycle_started_at,
            last_cycle_finished_at=m.last_cycle_finished_at,
            last_cycle_status=m.last_cycle_status,
            last_run_id=m.last_run_id,
            last_cycle_runtime_seconds=m.last_cycle_runtime_seconds,
            loaded_video_count=m.loaded_video_count,
            eligible_video_count=m.eligible_video_count,
            selected_capture_count=m.selected_capture_count,
            inserted_snapshot_count=m.inserted_snapshot_count,
            missing_count=m.missing_count,
            fetch_failed_count=m.fetch_failed_count,
            validation_failed_count=m.validation_failed_count,
            persistence_failed_count=m.persistence_failed_count,
            due_count_at_last_cycle=m.due_count_at_last_cycle,
            overdue_count_at_last_cycle=m.overdue_count_at_last_cycle,
            live_planner_due_count=m.live_planner_due_count,
            live_planner_overdue_count=m.live_planner_overdue_count,
            live_planner_requested=m.live_planner_requested,
        ),
        snapshots=SnapshotOperationsBlockResponse(
            latest_snapshot_at=overview.snapshots.latest_snapshot_at,
            snapshots_last_1h=overview.snapshots.snapshots_last_1h,
            snapshots_last_24h=overview.snapshots.snapshots_last_24h,
            unique_videos_snapshotted_last_24h=overview.snapshots.unique_videos_snapshotted_last_24h,
            daily_counts_last_7d=[
                SnapshotDailyCountResponse(date=row.date, count=row.count)
                for row in overview.snapshots.daily_counts_last_7d
            ],
        ),
        keyword_outcomes=KeywordOutcomeOperationsBlockResponse(
            attribution_mode=overview.keyword_outcomes.attribution_mode,
            horizon_hours=overview.keyword_outcomes.horizon_hours,
            tolerance_hours=overview.keyword_outcomes.tolerance_hours,
            attributed_observation_count=overview.keyword_outcomes.attributed_observation_count,
            pending_72h_count=overview.keyword_outcomes.pending_72h_count,
            matured_72h_count=overview.keyword_outcomes.matured_72h_count,
            valid_72h_outcome_count=overview.keyword_outcomes.valid_72h_outcome_count,
            missing_72h_outcome_count=overview.keyword_outcomes.missing_72h_outcome_count,
            matures_next_6h=overview.keyword_outcomes.matures_next_6h,
            matures_next_24h=overview.keyword_outcomes.matures_next_24h,
            matures_next_48h=overview.keyword_outcomes.matures_next_48h,
        ),
        errors=OperationsErrorsBlockResponse(
            discovery_last_cycle_error=overview.errors.discovery_last_cycle_error,
            monitoring_recent_error_summaries=overview.errors.monitoring_recent_error_summaries,
        ),
        recent_cycles=RecentCyclesBlockResponse(
            discovery=[_discovery_cycle_response(c) for c in overview.recent_cycles.discovery],
            monitoring=[
                MonitoringCycleHistoryItemResponse(
                    run_id=row.run_id,
                    started_at=row.started_at,
                    finished_at=row.finished_at,
                    runtime_seconds=row.runtime_seconds,
                    cycle_status=row.cycle_status,
                    loaded_video_count=row.loaded_video_count,
                    selected_request_count=row.selected_request_count,
                    inserted_snapshot_count=row.inserted_snapshot_count,
                    missing_count=row.missing_count,
                    fetch_failed_count=row.fetch_failed_count,
                    validation_failed_count=row.validation_failed_count,
                    persistence_failed_count=row.persistence_failed_count,
                    due_count=row.due_count,
                    overdue_count=row.overdue_count,
                    error_summary=row.error_summary,
                )
                for row in overview.recent_cycles.monitoring
            ],
        ),
    )


@router.get("/overview", response_model=OperationsOverviewResponse)
def operations_overview(
    db: Session = Depends(get_db),
    include_live_monitoring_planner: bool = Query(False),
    discovery_history_limit: int = Query(10, ge=1, le=50),
    monitoring_history_limit: int = Query(10, ge=1, le=50),
    outcome_attribution_mode: Literal["all_hits", "first_discovery"] = Query("all_hits"),
) -> OperationsOverviewResponse:
    overview = build_operations_overview(
        db,
        include_live_monitoring_planner=include_live_monitoring_planner,
        discovery_history_limit=discovery_history_limit,
        monitoring_history_limit=monitoring_history_limit,
        outcome_attribution_mode=outcome_attribution_mode,
    )
    return _to_response(overview)
