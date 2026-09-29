"""Append-only video snapshot persistence (Stage 1.11)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.orm import VideoSnapshot
from app.services.metrics import ensure_utc


@dataclass(frozen=True, slots=True)
class VideoSnapshotObservation:
    """Normalized input for one snapshot write (does not mutate RadarCandidate)."""

    video_id: str
    channel_id: str
    captured_at: datetime
    source: str
    fetch_status: str = "ok"
    run_id: str = ""
    experiment_id: str | None = None
    keyword: str | None = None
    published_at: datetime | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    subscribers: int | None = None
    content_format: str | None = None
    is_short: bool | None = None
    is_live: bool | None = None
    raw_metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SnapshotPersistResult:
    attempted_count: int
    inserted_count: int
    duplicate_count: int
    failed_count: int
    failures: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SnapshotValidationError:
    message: str


def derive_snapshot_metrics(
    *,
    views: int | None,
    published_at: datetime | None,
    captured_at: datetime,
    subscribers: int | None,
) -> tuple[float | None, float | None, float | None]:
    """Compute age_hours, vph, views_per_subscriber without fake zeros or 1h clamp."""
    age_hours: float | None = None
    vph: float | None = None
    views_per_subscriber: float | None = None

    if published_at is not None:
        published = ensure_utc(published_at)
        captured = ensure_utc(captured_at)
        if captured > published:
            elapsed_hours = (captured - published).total_seconds() / 3600.0
            if elapsed_hours > 0:
                age_hours = round(elapsed_hours, 4)

    if views is not None and age_hours is not None and age_hours > 0:
        vph = round(float(views) / age_hours, 4)

    if views is not None and subscribers is not None and subscribers > 0:
        views_per_subscriber = round(float(views) / float(subscribers), 4)

    return age_hours, vph, views_per_subscriber


def validate_snapshot_observation(
    observation: VideoSnapshotObservation,
) -> SnapshotValidationError | None:
    video_id = (observation.video_id or "").strip()
    channel_id = (observation.channel_id or "").strip()
    source = (observation.source or "").strip()
    if not video_id:
        return SnapshotValidationError("video_id is required")
    if not channel_id:
        return SnapshotValidationError("channel_id is required")
    if observation.captured_at is None:
        return SnapshotValidationError("captured_at is required")
    if not source:
        return SnapshotValidationError("source is required")
    if not (observation.fetch_status or "").strip():
        return SnapshotValidationError("fetch_status is required")

    for field_name, value in (
        ("views", observation.views),
        ("likes", observation.likes),
        ("comments", observation.comments),
        ("subscribers", observation.subscribers),
    ):
        if value is not None and value < 0:
            return SnapshotValidationError(f"{field_name} must be >= 0 when present")

    return None


def _row_values(row: VideoSnapshot) -> dict[str, Any]:
    return {
        "video_id": row.video_id,
        "channel_id": row.channel_id,
        "captured_at": row.captured_at,
        "published_at": row.published_at,
        "age_hours": row.age_hours,
        "views": row.views,
        "likes": row.likes,
        "comments": row.comments,
        "subscribers": row.subscribers,
        "vph": row.vph,
        "views_per_subscriber": row.views_per_subscriber,
        "source": row.source,
        "run_id": row.run_id,
        "experiment_id": row.experiment_id,
        "keyword": row.keyword,
        "content_format": row.content_format,
        "is_short": row.is_short,
        "is_live": row.is_live,
        "fetch_status": row.fetch_status,
        "raw_metadata": row.raw_metadata,
    }


def _insert_ignore(session: Session, row: VideoSnapshot):
    values = _row_values(row)
    dialect = session.bind.dialect.name if session.bind is not None else "sqlite"
    if dialect == "postgresql":
        stmt = pg_insert(VideoSnapshot).values(**values).on_conflict_do_nothing(
            constraint="uq_video_snapshot_capture",
        )
    else:
        stmt = sqlite_insert(VideoSnapshot).values(**values).on_conflict_do_nothing(
            index_elements=["video_id", "captured_at", "source", "run_id"],
        )
    return session.execute(stmt)


def observation_to_row(observation: VideoSnapshotObservation) -> VideoSnapshot:
    error = validate_snapshot_observation(observation)
    if error is not None:
        msg = error.message
        raise ValueError(msg)

    age_hours, vph, views_per_subscriber = derive_snapshot_metrics(
        views=observation.views,
        published_at=observation.published_at,
        captured_at=observation.captured_at,
        subscribers=observation.subscribers,
    )

    return VideoSnapshot(
        video_id=observation.video_id.strip(),
        channel_id=observation.channel_id.strip(),
        captured_at=ensure_utc(observation.captured_at),
        published_at=(
            ensure_utc(observation.published_at) if observation.published_at is not None else None
        ),
        age_hours=age_hours,
        views=observation.views,
        likes=observation.likes,
        comments=observation.comments,
        subscribers=observation.subscribers,
        vph=vph,
        views_per_subscriber=views_per_subscriber,
        source=observation.source.strip(),
        run_id=(observation.run_id or "").strip(),
        experiment_id=observation.experiment_id,
        keyword=observation.keyword,
        content_format=observation.content_format,
        is_short=observation.is_short,
        is_live=observation.is_live,
        fetch_status=observation.fetch_status.strip(),
        raw_metadata=observation.raw_metadata,
    )


def persist_video_snapshot(
    session: Session,
    observation: VideoSnapshotObservation,
) -> tuple[VideoSnapshot | None, SnapshotValidationError | None, bool]:
    """
    Insert one snapshot.

    Returns (row, validation_error, is_duplicate).
    """
    validation = validate_snapshot_observation(observation)
    if validation is not None:
        return None, validation, False

    row = observation_to_row(observation)
    result = _insert_ignore(session, row)
    inserted = bool(result.rowcount and result.rowcount > 0)
    session.flush()
    if not inserted:
        return None, None, True
    return row, None, False


def persist_video_snapshots(
    session: Session,
    observations: Sequence[VideoSnapshotObservation],
) -> SnapshotPersistResult:
    attempted = len(observations)
    inserted = 0
    duplicate = 0
    failed = 0
    failures: list[str] = []

    for index, observation in enumerate(observations):
        validation = validate_snapshot_observation(observation)
        if validation is not None:
            failed += 1
            failures.append(f"index={index}: {validation.message}")
            continue

        row = observation_to_row(observation)
        result = _insert_ignore(session, row)
        if result.rowcount and result.rowcount > 0:
            inserted += 1
        else:
            duplicate += 1

    session.flush()
    return SnapshotPersistResult(
        attempted_count=attempted,
        inserted_count=inserted,
        duplicate_count=duplicate,
        failed_count=failed,
        failures=tuple(failures),
    )


def get_snapshots_for_video(
    session: Session,
    video_id: str,
) -> list[VideoSnapshot]:
    stmt = (
        select(VideoSnapshot)
        .where(VideoSnapshot.video_id == video_id)
        .order_by(VideoSnapshot.captured_at.asc())
    )
    return list(session.scalars(stmt).all())


_LATEST_SNAPSHOT_CHUNK = 400


def get_latest_snapshots_for_videos(
    session: Session,
    video_ids: Sequence[str],
) -> dict[str, VideoSnapshot]:
    """Latest snapshot per video_id (bounded SQL, not full history scan)."""
    ids = list(dict.fromkeys(video_ids))
    if not ids:
        return {}
    latest: dict[str, VideoSnapshot] = {}
    for start in range(0, len(ids), _LATEST_SNAPSHOT_CHUNK):
        chunk = ids[start : start + _LATEST_SNAPSHOT_CHUNK]
        max_captured = (
            select(
                VideoSnapshot.video_id.label("video_id"),
                func.max(VideoSnapshot.captured_at).label("max_captured_at"),
            )
            .where(VideoSnapshot.video_id.in_(chunk))
            .group_by(VideoSnapshot.video_id)
            .subquery()
        )
        stmt = select(VideoSnapshot).join(
            max_captured,
            (VideoSnapshot.video_id == max_captured.c.video_id)
            & (VideoSnapshot.captured_at == max_captured.c.max_captured_at),
        )
        for row in session.scalars(stmt).all():
            previous = latest.get(row.video_id)
            if previous is None or row.captured_at > previous.captured_at:
                latest[row.video_id] = row
    return latest


def get_latest_snapshot_for_video(
    session: Session,
    video_id: str,
) -> VideoSnapshot | None:
    stmt = (
        select(VideoSnapshot)
        .where(VideoSnapshot.video_id == video_id)
        .order_by(VideoSnapshot.captured_at.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def get_snapshots_for_channel(
    session: Session,
    channel_id: str,
    *,
    captured_from: datetime | None = None,
    captured_to: datetime | None = None,
) -> list[VideoSnapshot]:
    stmt = select(VideoSnapshot).where(VideoSnapshot.channel_id == channel_id)
    if captured_from is not None:
        stmt = stmt.where(VideoSnapshot.captured_at >= ensure_utc(captured_from))
    if captured_to is not None:
        stmt = stmt.where(VideoSnapshot.captured_at <= ensure_utc(captured_to))
    stmt = stmt.order_by(VideoSnapshot.captured_at.asc())
    return list(session.scalars(stmt).all())


def get_snapshots_for_videos(
    session: Session,
    video_ids: Sequence[str],
) -> list[VideoSnapshot]:
    if not video_ids:
        return []
    stmt = (
        select(VideoSnapshot)
        .where(VideoSnapshot.video_id.in_(list(video_ids)))
        .order_by(VideoSnapshot.video_id.asc(), VideoSnapshot.captured_at.asc())
    )
    return list(session.scalars(stmt).all())


def find_snapshot_by_capture_run_key(
    session: Session,
    *,
    video_id: str,
    source: str,
    run_id: str,
) -> VideoSnapshot | None:
    """Lookup prior snapshot for executor idempotency (stable run_id per checkpoint)."""
    stmt = (
        select(VideoSnapshot)
        .where(
            VideoSnapshot.video_id == video_id,
            VideoSnapshot.source == source,
            VideoSnapshot.run_id == run_id,
        )
        .limit(1)
    )
    return session.scalars(stmt).first()


def get_nearest_snapshot_by_age_hours(
    session: Session,
    video_id: str,
    target_age_hours: float,
) -> VideoSnapshot | None:
    snapshots = [
        row
        for row in get_snapshots_for_video(session, video_id)
        if row.age_hours is not None
    ]
    if not snapshots:
        return None
    return min(snapshots, key=lambda row: abs(float(row.age_hours) - target_age_hours))
