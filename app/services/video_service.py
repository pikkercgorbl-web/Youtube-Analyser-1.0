from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Float, Select, case, cast, func, select
from sqlalchemy.orm import Session

from app.models.orm import Channel, Video
from app.models.schemas import (
    SortOrder,
    VideoCreate,
    VideoSearchParams,
    VideoSortField,
    VideoUpdate,
)


@dataclass(frozen=True, slots=True)
class VideoSearchRow:
    """Single row returned by advanced video search."""

    video: Video
    channel: Channel
    virality_percent: float


def calc_virality_percent(views_count: int, subscribers_count: int) -> float:
    """Return virality as (views / max(subscribers, 1)) × 100."""
    denominator = max(subscribers_count, 1)
    return (views_count / denominator) * 100.0


def _virality_percent_sql():
    """SQL expression: (views / max(subscribers, 1)) × 100."""
    safe_subscribers = cast(
        case((Channel.subscribers_count < 1, 1), else_=Channel.subscribers_count),
        Float,
    )
    return cast(Video.views_count, Float) / safe_subscribers * 100.0


class VideoService:
    """Business logic for YouTube videos."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_by_id(self, video_id: str) -> Video | None:
        # TODO: fetch channel with joinedload if needed
        return self._db.get(Video, video_id)

    def list_by_channel(self, channel_id: str, *, limit: int = 50, offset: int = 0) -> list[Video]:
        stmt = (
            select(Video)
            .where(Video.channel_id == channel_id)
            .order_by(Video.published_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self._db.scalars(stmt).all())

    def create(self, payload: VideoCreate) -> Video:
        # TODO: verify channel exists, persist video
        raise NotImplementedError

    def update(self, video_id: str, payload: VideoUpdate) -> Video | None:
        # TODO: partial update
        raise NotImplementedError

    def advanced_search(self, params: VideoSearchParams) -> tuple[list[VideoSearchRow], int]:
        """Search videos with deep filters and optional viral anomaly detection."""
        virality_expr = _virality_percent_sql()
        base_stmt = self._build_search_statement(params, virality_expr)

        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total = self._db.scalar(count_stmt) or 0

        ordered_stmt = self._apply_sort(base_stmt, params, virality_expr)
        page_stmt = ordered_stmt.limit(params.limit).offset(params.offset)

        rows = self._db.execute(page_stmt).all()
        results = [
            VideoSearchRow(
                video=video,
                channel=channel,
                virality_percent=float(virality),
            )
            for video, channel, virality in rows
        ]
        return results, total

    def find_viral_anomalies(
        self,
        params: VideoSearchParams,
        *,
        min_virality_percent: float = 1000.0,
    ) -> tuple[list[VideoSearchRow], int]:
        """Find videos with abnormally high views relative to channel subscribers."""
        anomaly_params = params.model_copy(
            update={
                "anomalies_only": True,
                "min_virality_percent": min_virality_percent,
                "sort_by": VideoSortField.VIRALITY,
                "sort_order": SortOrder.DESC,
            },
        )
        return self.advanced_search(anomaly_params)

    def _build_search_statement(
        self,
        params: VideoSearchParams,
        virality_expr,
    ) -> Select[tuple[Video, Channel, float]]:
        stmt = (
            select(Video, Channel, virality_expr.label("virality_percent"))
            .join(Channel, Video.channel_id == Channel.id)
        )

        if params.published_from is not None:
            stmt = stmt.where(Video.published_at >= params.published_from)
        if params.published_to is not None:
            stmt = stmt.where(Video.published_at <= params.published_to)
        if params.duration_min is not None:
            stmt = stmt.where(Video.duration_seconds >= params.duration_min)
        if params.duration_max is not None:
            stmt = stmt.where(Video.duration_seconds <= params.duration_max)
        if params.views_min is not None:
            stmt = stmt.where(Video.views_count >= params.views_min)
        if params.views_max is not None:
            stmt = stmt.where(Video.views_count <= params.views_max)
        if params.channel_id is not None:
            stmt = stmt.where(Video.channel_id == params.channel_id)
        if params.anomalies_only:
            stmt = stmt.where(virality_expr >= params.min_virality_percent)

        return stmt

    def _apply_sort(
        self,
        stmt: Select[tuple[Video, Channel, float]],
        params: VideoSearchParams,
        virality_expr,
    ) -> Select[tuple[Video, Channel, float]]:
        descending = params.sort_order == SortOrder.DESC
        sort_by = params.sort_by
        if params.anomalies_only and sort_by == VideoSortField.PUBLISHED_AT:
            sort_by = VideoSortField.VIRALITY

        if sort_by == VideoSortField.VIEWS_COUNT:
            order_col = Video.views_count
        elif sort_by == VideoSortField.VIRALITY:
            order_col = virality_expr
        else:
            order_col = Video.published_at

        return stmt.order_by(order_col.desc() if descending else order_col.asc())
