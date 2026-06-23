from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.schemas import (
    SortOrder,
    VideoSearchItem,
    VideoSearchParams,
    VideoSearchResponse,
    VideoSortField,
)
from app.services.video_service import VideoSearchRow, VideoService

router = APIRouter()


def get_video_service(db: Session = Depends(get_db)) -> VideoService:
    return VideoService(db)


def _row_to_item(row: VideoSearchRow) -> VideoSearchItem:
    return VideoSearchItem(
        id=row.video.id,
        title=row.video.title,
        views_count=row.video.views_count,
        likes_count=row.video.likes_count,
        comments_count=row.video.comments_count,
        published_at=row.video.published_at,
        duration_seconds=row.video.duration_seconds,
        channel_id=row.video.channel_id,
        updated_at=row.video.updated_at,
        channel_title=row.channel.title,
        channel_subscribers_count=row.channel.subscribers_count,
        virality_percent=round(row.virality_percent, 2),
    )


def _run_search(
    service: VideoService,
    params: VideoSearchParams,
) -> VideoSearchResponse:
    rows, total = service.advanced_search(params)
    return VideoSearchResponse(
        items=[_row_to_item(row) for row in rows],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.get("/search", response_model=VideoSearchResponse)
def advanced_video_search(
    published_from: datetime | None = Query(default=None, description="Upload date lower bound"),
    published_to: datetime | None = Query(default=None, description="Upload date upper bound"),
    duration_min: int | None = Query(default=None, ge=0, description="Min duration in seconds"),
    duration_max: int | None = Query(default=None, ge=0, description="Max duration in seconds"),
    views_min: int | None = Query(default=None, ge=0),
    views_max: int | None = Query(default=None, ge=0),
    channel_id: str | None = Query(default=None, max_length=64),
    anomalies_only: bool = Query(
        default=False,
        description="Filter viral anomalies: views/subscribers above threshold",
    ),
    min_virality_percent: float = Query(
        default=1000.0,
        ge=0,
        description="Min virality % when anomalies_only=true. 1000 = 10× subscribers.",
    ),
    sort_by: VideoSortField = Query(default=VideoSortField.PUBLISHED_AT),
    sort_order: SortOrder = Query(default=SortOrder.DESC),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: VideoService = Depends(get_video_service),
) -> VideoSearchResponse:
    """Advanced video search with deep filters and optional viral anomaly ranking."""
    params = VideoSearchParams(
        published_from=published_from,
        published_to=published_to,
        duration_min=duration_min,
        duration_max=duration_max,
        views_min=views_min,
        views_max=views_max,
        channel_id=channel_id,
        anomalies_only=anomalies_only,
        min_virality_percent=min_virality_percent,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )
    return _run_search(service, params)


@router.get("/anomalies", response_model=VideoSearchResponse)
def viral_anomalies_search(
    published_from: datetime | None = Query(default=None),
    published_to: datetime | None = Query(default=None),
    duration_min: int | None = Query(default=None, ge=0),
    duration_max: int | None = Query(default=None, ge=0),
    views_min: int | None = Query(default=None, ge=0),
    views_max: int | None = Query(default=None, ge=0),
    channel_id: str | None = Query(default=None, max_length=64),
    min_virality_percent: float = Query(default=1000.0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: VideoService = Depends(get_video_service),
) -> VideoSearchResponse:
    """Shortcut for viral anomaly search sorted by virality coefficient."""
    params = VideoSearchParams(
        published_from=published_from,
        published_to=published_to,
        duration_min=duration_min,
        duration_max=duration_max,
        views_min=views_min,
        views_max=views_max,
        channel_id=channel_id,
        limit=limit,
        offset=offset,
    )
    rows, total = service.find_viral_anomalies(
        params,
        min_virality_percent=min_virality_percent,
    )
    return VideoSearchResponse(
        items=[_row_to_item(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
