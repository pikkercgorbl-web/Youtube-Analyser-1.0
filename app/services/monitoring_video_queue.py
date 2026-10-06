"""Monitoring video queue read model — persist at cycle, SQL paginate for API (Stage 1.20E.3)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.models.orm import Channel, MonitoringVideoQueueEntry, Video, VideoSnapshot
from app.services.metrics import ensure_utc
from app.services.monitoring_cycle_run_storage import get_latest_monitoring_cycle_run
from app.services.monitoring_radar_eligibility import monitoring_video_eligible
from app.services.video_format_api_verification import load_api_format_confirmed_video_ids
from app.services.video_snapshot_storage import get_latest_snapshots_for_videos

MonitoringListStatus = Literal["due", "overdue", "pending", "active", "stopped"]
MonitoringSort = Literal[
    "priority",
    "breakout_v1",
    "vph_desc",
    "views_desc",
    "age_asc",
    "latest_snapshot_desc",
]

QueueListSource = Literal["cycle_snapshot", "live_planner", "unavailable"]


@dataclass(frozen=True, slots=True)
class MonitoringVideoListMeta:
    queue_run_id: str | None
    queue_generated_at: datetime | None
    queue_source: QueueListSource


@dataclass
class MonitoringQueuePageRow:
    """List row built from persisted queue + optional fresh latest snapshot."""

    video_id: str
    channel_id: str
    title: str | None
    channel_title: str | None
    tier: str
    current_views: int | None
    current_vph: float | None
    age_hours: float | None
    published_at: datetime
    latest_snapshot_at: datetime | None
    next_checkpoint_hours: int | None
    monitoring_status: str
    due_checkpoint_hours: list[int]
    overdue_checkpoint_hours: list[int]
    baseline_status: str | None
    vph_vs_channel_median: float | None
    content_format: str | None


def _filtered_queue_stmt(
    run_id: str,
    *,
    tier: str | None,
    status: MonitoringListStatus | None,
    channel_id: str | None,
    keyword: str | None,
):
    needle = keyword.strip().lower() if keyword else ""
    if needle:
        stmt = (
            select(MonitoringVideoQueueEntry)
            .join(Video, Video.id == MonitoringVideoQueueEntry.video_id)
            .where(MonitoringVideoQueueEntry.run_id == run_id)
        )
    else:
        stmt = select(MonitoringVideoQueueEntry).where(MonitoringVideoQueueEntry.run_id == run_id)
    return _apply_filters(stmt, tier=tier, status=status, channel_id=channel_id, keyword=keyword)


def _queue_base_stmt(run_id: str):
    return (
        select(MonitoringVideoQueueEntry, Video, Channel)
        .join(Video, Video.id == MonitoringVideoQueueEntry.video_id)
        .join(Channel, Channel.id == MonitoringVideoQueueEntry.channel_id)
        .where(MonitoringVideoQueueEntry.run_id == run_id)
    )


def _apply_status_filter(stmt, status: MonitoringListStatus):
    if status == "overdue":
        return stmt.where(MonitoringVideoQueueEntry.has_overdue_checkpoint.is_(True))
    if status == "due":
        return stmt.where(MonitoringVideoQueueEntry.has_due_checkpoint.is_(True))
    if status == "pending":
        return stmt.where(
            MonitoringVideoQueueEntry.monitoring_status == "active",
            MonitoringVideoQueueEntry.has_due_checkpoint.is_(False),
            MonitoringVideoQueueEntry.has_overdue_checkpoint.is_(False),
            MonitoringVideoQueueEntry.has_pending_checkpoint.is_(True),
        )
    if status == "active":
        return stmt.where(MonitoringVideoQueueEntry.monitoring_status == "active")
    if status == "stopped":
        return stmt.where(MonitoringVideoQueueEntry.monitoring_status == "stopped")
    return stmt


def _apply_filters(
    stmt,
    *,
    tier: str | None,
    status: MonitoringListStatus | None,
    channel_id: str | None,
    keyword: str | None,
):
    if tier is not None:
        stmt = stmt.where(MonitoringVideoQueueEntry.tier == tier.upper())
    if channel_id is not None:
        stmt = stmt.where(MonitoringVideoQueueEntry.channel_id == channel_id)
    if status is not None:
        stmt = _apply_status_filter(stmt, status)
    if keyword:
        needle = keyword.strip().lower()
        if needle:
            pattern = f"%{needle}%"
            stmt = stmt.where(
                or_(
                    func.lower(Video.title).like(pattern),
                    func.lower(MonitoringVideoQueueEntry.video_id).like(pattern),
                ),
            )
    return stmt


def _apply_sort(stmt, sort: MonitoringSort):
    q = MonitoringVideoQueueEntry
    if sort == "priority":
        return stmt.order_by(q.priority_rank.asc(), q.video_id.asc())
    if sort == "vph_desc":
        return stmt.order_by(q.current_vph.desc().nulls_last(), q.video_id.asc())
    if sort == "views_desc":
        return stmt.order_by(q.current_views.desc().nulls_last(), q.video_id.asc())
    if sort == "age_asc":
        return stmt.order_by(q.age_hours.asc().nulls_last(), q.video_id.asc())
    if sort == "latest_snapshot_desc":
        return stmt.order_by(q.latest_snapshot_at.desc().nulls_last(), q.video_id.asc())
    return stmt.order_by(q.priority_rank.asc(), q.video_id.asc())


def _filter_eligible_queue_rows(
    session: Session,
    rows: list[tuple[MonitoringVideoQueueEntry, Video, Channel]],
) -> list[tuple[MonitoringVideoQueueEntry, Video, Channel]]:
    if not rows:
        return []
    video_ids = [entry.video_id for entry, _, _ in rows]
    latest_by_video = get_latest_snapshots_for_videos(session, video_ids)
    confirmed = load_api_format_confirmed_video_ids(session, video_ids)
    kept: list[tuple[MonitoringVideoQueueEntry, Video, Channel]] = []
    for entry, video, channel in rows:
        if monitoring_video_eligible(
            video=video,
            channel=channel,
            latest_snapshot=latest_by_video.get(entry.video_id),
            confirmed_regular_ids=confirmed,
        ):
            kept.append((entry, video, channel))
    return kept


def count_queue_videos(
    session: Session,
    run_id: str,
    *,
    tier: str | None = None,
    status: MonitoringListStatus | None = None,
    channel_id: str | None = None,
    keyword: str | None = None,
) -> int:
    stmt = _queue_base_stmt(run_id)
    stmt = _apply_filters(stmt, tier=tier, status=status, channel_id=channel_id, keyword=keyword)
    rows = list(session.execute(stmt).all())
    return len(_filter_eligible_queue_rows(session, rows))


def list_queue_videos_page(
    session: Session,
    run_id: str,
    *,
    tier: str | None = None,
    status: MonitoringListStatus | None = None,
    channel_id: str | None = None,
    keyword: str | None = None,
    sort: MonitoringSort = "priority",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MonitoringQueuePageRow], int]:
    total = count_queue_videos(
        session,
        run_id,
        tier=tier,
        status=status,
        channel_id=channel_id,
        keyword=keyword,
    )
    if total == 0:
        return [], 0

    stmt = _queue_base_stmt(run_id)
    stmt = _apply_filters(stmt, tier=tier, status=status, channel_id=channel_id, keyword=keyword)
    stmt = _apply_sort(stmt, sort)
    all_rows: list[tuple[MonitoringVideoQueueEntry, Video, Channel]] = list(session.execute(stmt).all())
    eligible_rows = _filter_eligible_queue_rows(session, all_rows)
    page_limit = max(1, min(limit, 200))
    page_entries = eligible_rows[max(0, offset) : max(0, offset) + page_limit]
    video_ids = [entry.video_id for entry, _, _ in page_entries]
    latest_by_video = get_latest_snapshots_for_videos(session, video_ids) if video_ids else {}

    rows: list[MonitoringQueuePageRow] = []
    for entry, video, channel in page_entries:
        latest: VideoSnapshot | None = latest_by_video.get(entry.video_id)
        views = entry.current_views
        vph = entry.current_vph
        latest_at = entry.latest_snapshot_at
        if latest is not None:
            if latest.views is not None:
                views = latest.views
            if latest.vph is not None:
                vph = latest.vph
            latest_at = latest.captured_at
        rows.append(
            MonitoringQueuePageRow(
                video_id=entry.video_id,
                channel_id=entry.channel_id,
                title=video.title,
                channel_title=channel.title,
                tier=entry.tier,
                current_views=views,
                current_vph=vph,
                age_hours=entry.age_hours,
                published_at=ensure_utc(entry.published_at),
                latest_snapshot_at=latest_at,
                next_checkpoint_hours=entry.next_checkpoint_hours,
                monitoring_status=entry.monitoring_status,
                due_checkpoint_hours=json.loads(entry.due_checkpoint_hours_json or "[]"),
                overdue_checkpoint_hours=json.loads(entry.overdue_checkpoint_hours_json or "[]"),
                baseline_status=entry.channel_velocity_baseline_status,
                vph_vs_channel_median=entry.vph_vs_channel_median,
                content_format=entry.content_format,
            ),
        )
    return rows, total


def resolve_queue_list_context(
    session: Session,
) -> tuple[str | None, datetime | None, bool]:
    """Latest completed cycle run_id with a non-empty queue, if any."""
    latest = get_latest_monitoring_cycle_run(session)
    if latest is None or latest.finished_at is None:
        return None, None, False
    if latest.cycle_status not in ("ok", "partial"):
        return None, None, False
    row_count = session.scalar(
        select(func.count())
        .select_from(MonitoringVideoQueueEntry)
        .where(MonitoringVideoQueueEntry.run_id == latest.run_id),
    )
    if not row_count:
        return None, latest.finished_at, False
    return latest.run_id, latest.finished_at, True


def queue_list_meta(
    *,
    run_id: str | None,
    generated_at: datetime | None,
    source: QueueListSource,
) -> MonitoringVideoListMeta:
    return MonitoringVideoListMeta(
        queue_run_id=run_id,
        queue_generated_at=generated_at,
        queue_source=source,
    )
