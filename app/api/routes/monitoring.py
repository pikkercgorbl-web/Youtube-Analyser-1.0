"""Monitoring worker read API (Stage 1.14A)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.schemas import (
    MonitoringChannelBaselineResponse,
    MonitoringCheckpointResponse,
    MonitoringCycleListResponse,
    MonitoringCycleResponse,
    MonitoringLatestCycleResponse,
    MonitoringOverviewResponse,
    MonitoringSnapshotResponse,
    MonitoringVideoDetailResponse,
    MonitoringVideoListItem,
    MonitoringVideoListResponse,
    MonitoringWorkerStatusResponse,
)
from app.services.breakout_ranking_service import (
    BREAKOUT_RANKING_REASON,
    BREAKOUT_RANKING_SIGNAL,
    BREAKOUT_RANK_VERSION,
)
from app.services.monitoring_api_service import (
    BreakoutVideoListRow,
    MonitoringEnrichedVideo,
    MonitoringListStatus,
    MonitoringSort,
    get_monitoring_cycle_history,
    get_monitoring_overview,
    get_monitoring_video_detail,
    get_monitoring_worker_status,
    get_video_baseline_for_detail,
    list_monitoring_videos,
    list_video_monitoring_snapshots,
)

router = APIRouter()

_VALID_TIERS = {"A", "B", "C"}
_VALID_STATUSES = {"due", "overdue", "pending", "active", "stopped"}
_VALID_SORTS = {"priority", "breakout_v1", "vph_desc", "views_desc", "age_asc", "latest_snapshot_desc"}


def _list_item(row: MonitoringEnrichedVideo) -> MonitoringVideoListItem:
    due_hours = [cp.target_age_hours for cp in row.plan.due_checkpoints if cp.status == "due"]
    overdue_hours = [cp.target_age_hours for cp in row.plan.due_checkpoints if cp.status == "overdue"]
    return MonitoringVideoListItem(
        video_id=row.state.video_id,
        channel_id=row.state.channel_id,
        title=row.title,
        channel_title=row.channel_title,
        tier=row.decision.tier.value,
        current_views=row.current_views,
        current_vph=row.current_vph,
        age_hours=row.state.age_hours,
        published_at=row.state.published_at,
        latest_snapshot_at=row.latest_snapshot.captured_at if row.latest_snapshot else None,
        next_checkpoint_hours=row.plan.next_checkpoint_hours,
        monitoring_status=row.plan.monitoring_status,
        due_checkpoint_hours=due_hours,
        overdue_checkpoint_hours=overdue_hours,
        baseline_status=row.state.channel_velocity_baseline_status,
        vph_vs_channel_median=row.state.vph_vs_channel_median,
        content_format=row.state.content_format,
    )


def _breakout_list_item(row: BreakoutVideoListRow) -> MonitoringVideoListItem:
    monitoring_status = "active" if row.in_active_capture_pool else "not_in_capture_pool"
    return MonitoringVideoListItem(
        video_id=row.state.video_id,
        channel_id=row.state.channel_id,
        title=row.title,
        channel_title=row.channel_title,
        tier=row.decision.tier.value,
        current_views=row.current_views,
        current_vph=row.current_vph,
        age_hours=row.state.age_hours,
        published_at=row.state.published_at,
        latest_snapshot_at=row.latest_snapshot.captured_at if row.latest_snapshot else None,
        next_checkpoint_hours=None,
        monitoring_status=monitoring_status,
        due_checkpoint_hours=[],
        overdue_checkpoint_hours=[],
        baseline_status=row.state.channel_velocity_baseline_status,
        vph_vs_channel_median=row.state.vph_vs_channel_median,
        content_format=row.state.content_format,
        breakout_rank=row.breakout_rank,
        breakout_rank_version=BREAKOUT_RANK_VERSION,
        breakout_ranking_signal=BREAKOUT_RANKING_SIGNAL,
        breakout_ranking_value=row.breakout_ranking_value,
        breakout_ranking_reason=BREAKOUT_RANKING_REASON,
        breakout_ranking_excluded_reason=None,
        in_active_capture_pool=row.in_active_capture_pool,
    )


@router.get("/status", response_model=MonitoringWorkerStatusResponse)
def monitoring_status(db: Session = Depends(get_db)) -> MonitoringWorkerStatusResponse:
    data = get_monitoring_worker_status(db)
    return MonitoringWorkerStatusResponse(**asdict(data))


@router.get("/overview", response_model=MonitoringOverviewResponse)
def monitoring_overview(db: Session = Depends(get_db)) -> MonitoringOverviewResponse:
    data = get_monitoring_overview(db)
    latest = None
    if data.latest_cycle is not None:
        cycle = data.latest_cycle
        latest = MonitoringLatestCycleResponse(
            run_id=cycle.run_id,
            started_at=cycle.started_at,
            finished_at=cycle.finished_at,
            runtime_seconds=cycle.runtime_seconds,
            cycle_status=cycle.cycle_status,
            loaded_video_count=cycle.loaded_video_count,
            selected_request_count=cycle.selected_request_count,
            inserted_snapshot_count=cycle.inserted_snapshot_count,
            duplicate_snapshot_count=cycle.duplicate_snapshot_count,
            missing_count=cycle.missing_count,
            fetch_failed_count=cycle.fetch_failed_count,
            validation_failed_count=cycle.validation_failed_count,
            persistence_failed_count=cycle.persistence_failed_count,
        )
    return MonitoringOverviewResponse(
        active_monitored_count=data.active_monitored_count,
        tier_counts=data.tier_counts,
        unmonitored_count=data.unmonitored_count,
        due_count=data.due_count,
        overdue_count=data.overdue_count,
        pending_count=data.pending_count,
        stopped_count=data.stopped_count,
        latest_cycle=latest,
    )


@router.get("/videos", response_model=MonitoringVideoListResponse)
def monitoring_videos(
    tier: str | None = Query(default=None, description="Filter tier A, B, or C"),
    monitoring_status: str | None = Query(
        default=None,
        alias="status",
        description="due|overdue|pending|active|stopped",
    ),
    channel_id: str | None = Query(default=None, max_length=64),
    keyword: str | None = Query(default=None, max_length=128),
    sort: str = Query(default="priority"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> MonitoringVideoListResponse:
    if tier is not None and tier.upper() not in _VALID_TIERS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tier filter")
    if monitoring_status is not None and monitoring_status.lower() not in _VALID_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status filter")
    if sort not in _VALID_SORTS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid sort")

    status_filter: MonitoringListStatus | None = (
        monitoring_status.lower() if monitoring_status else None
    )  # type: ignore[assignment]
    rows, total = list_monitoring_videos(
        db,
        tier=tier,
        status=status_filter,
        channel_id=channel_id,
        keyword=keyword,
        sort=sort,  # type: ignore[arg-type]
        limit=limit,
        offset=offset,
    )
    if sort == "breakout_v1":
        items = [_breakout_list_item(row) for row in rows]  # type: ignore[arg-type]
    else:
        items = [_list_item(row) for row in rows]  # type: ignore[arg-type]
    return MonitoringVideoListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/videos/{video_id}", response_model=MonitoringVideoDetailResponse)
def monitoring_video_detail(
    video_id: str,
    db: Session = Depends(get_db),
) -> MonitoringVideoDetailResponse:
    row = get_monitoring_video_detail(db, video_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    baseline_block: MonitoringChannelBaselineResponse | None = None
    baseline = get_video_baseline_for_detail(db, row)
    if baseline is not None:
        baseline_block = MonitoringChannelBaselineResponse(
            baseline_status=baseline.baseline_status,
            comparable_video_count=baseline.comparable_video_count,
            median_vph=baseline.median_vph,
            p75_vph=baseline.p75_vph,
            p90_vph=baseline.p90_vph,
            vph_vs_channel_median=baseline.vph_vs_channel_median,
            vph_vs_channel_p75=baseline.vph_vs_channel_p75,
        )

    subscribers = row.latest_snapshot.subscribers if row.latest_snapshot else None
    vps = row.latest_snapshot.views_per_subscriber if row.latest_snapshot else None

    return MonitoringVideoDetailResponse(
        video_id=row.state.video_id,
        channel_id=row.state.channel_id,
        title=row.title,
        channel_title=row.channel_title,
        published_at=row.state.published_at,
        content_format=row.state.content_format,
        views=row.current_views,
        subscribers=subscribers,
        vph=row.current_vph,
        views_per_subscriber=vps,
        age_hours=row.state.age_hours,
        tier=row.decision.tier.value,
        monitoring_status=row.plan.monitoring_status,
        checkpoints=[
            MonitoringCheckpointResponse(
                target_age_hours=cp.target_age_hours,
                status=cp.status,
                matched_snapshot_age_hours=cp.matched_snapshot_age_hours,
                due_since_hours=cp.due_since_hours,
                expires_at_age_hours=cp.expires_at_age_hours,
                recommended_action=cp.recommended_action,
            )
            for cp in row.plan.checkpoints
        ],
        next_checkpoint_hours=row.plan.next_checkpoint_hours,
        stop_reason=row.plan.stop_reason,
        channel_baseline=baseline_block,
    )


@router.get("/videos/{video_id}/snapshots", response_model=list[MonitoringSnapshotResponse])
def monitoring_video_snapshots(
    video_id: str,
    limit: int | None = Query(default=None, ge=1, le=500),
    captured_from: datetime | None = Query(default=None, alias="from"),
    captured_to: datetime | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
) -> list[MonitoringSnapshotResponse]:
    from app.models.orm import Video

    if db.get(Video, video_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    rows = list_video_monitoring_snapshots(
        db,
        video_id,
        limit=limit,
        captured_from=captured_from,
        captured_to=captured_to,
    )
    return [
        MonitoringSnapshotResponse(
            captured_at=row.captured_at,
            age_hours=row.age_hours,
            views=row.views,
            likes=row.likes,
            comments=row.comments,
            subscribers=row.subscribers,
            vph=row.vph,
            views_per_subscriber=row.views_per_subscriber,
            source=row.source,
            run_id=row.run_id,
            fetch_status=row.fetch_status,
        )
        for row in rows
    ]


@router.get("/cycles", response_model=MonitoringCycleListResponse)
def monitoring_cycles(
    limit: int = Query(default=20, ge=1, le=100),
    cycle_status: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> MonitoringCycleListResponse:
    rows = get_monitoring_cycle_history(db, limit=limit, cycle_status=cycle_status)
    items = [
        MonitoringCycleResponse(
            run_id=row.run_id,
            started_at=row.started_at,
            finished_at=row.finished_at,
            runtime_seconds=row.runtime_seconds,
            cycle_status=row.cycle_status,
            loaded=row.loaded_video_count,
            tier_a=row.tier_a_count,
            tier_b=row.tier_b_count,
            tier_c=row.tier_c_count,
            due=row.due_count,
            overdue=row.overdue_count,
            selected=row.selected_request_count,
            deferred=row.deferred_request_count,
            inserted=row.inserted_snapshot_count,
            missing=row.missing_count,
            fetch_failed=row.fetch_failed_count,
            validation_failed=row.validation_failed_count,
            persistence_failed=row.persistence_failed_count,
            duplicate_snapshot_count=row.duplicate_snapshot_count,
        )
        for row in rows
    ]
    return MonitoringCycleListResponse(items=items, limit=limit)
