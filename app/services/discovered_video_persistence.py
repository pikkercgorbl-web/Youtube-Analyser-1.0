"""Upsert discovered regular videos for monitoring handoff (Stage 1.15A)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.orm import Session

from app.integrations.youtube.client import VideoSearchModel
from app.models.orm import Channel, Video, VideoFormat
from app.services.metrics import ensure_utc, utc_now
from app.services.video_filter_service import parse_relative_published_date

PersistOutcome = Literal["inserted", "updated", "skipped_invalid", "skipped_short", "skipped_live"]


@dataclass(frozen=True, slots=True)
class VideoPersistResult:
    video_id: str
    outcome: PersistOutcome


def _infer_content_format(video: VideoSearchModel) -> VideoFormat:
    if video.is_short:
        return VideoFormat.SHORT
    if video.is_live:
        return VideoFormat.LIVE
    return VideoFormat.MEDIUM


def _parse_duration_seconds(duration_text: str) -> int:
    text = (duration_text or "").strip()
    if not text:
        return 0
    parts = text.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = (int(p) for p in parts)
            return hours * 3600 + minutes * 60 + seconds
        if len(parts) == 2:
            minutes, seconds = (int(p) for p in parts)
            return minutes * 60 + seconds
    except ValueError:
        return 0
    return 0


def _published_at_from_search(video: VideoSearchModel) -> datetime | None:
    published_at = parse_relative_published_date(video.published_text)
    min_dt = datetime.min.replace(tzinfo=timezone.utc)
    if published_at <= min_dt:
        return None
    return ensure_utc(published_at)


def _dialect_insert(session: Session):
    name = session.get_bind().dialect.name
    if name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert

        return insert
    if name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert

        return insert
    raise RuntimeError(f"Channel upsert requires postgresql or sqlite, got {name!r}")


def _upsert_discovered_channel(
    session: Session,
    channel_id: str,
    *,
    title: str,
    subscribers_count: int,
    topic: str | None = None,
    custom_url: str | None = None,
    created_at: datetime,
) -> None:
    """Insert or update ``Channel`` atomically (PostgreSQL ``ON CONFLICT``)."""
    incoming_title = (title or "").strip()
    title_for_insert = incoming_title or channel_id
    incoming_subs = max(subscribers_count, 0)
    incoming_topic = (topic or "").strip()
    incoming_custom_url = (custom_url or "").strip()

    table = Channel.__table__
    insert_fn = _dialect_insert(session)
    insert_stmt = insert_fn(Channel).values(
        id=channel_id,
        title=title_for_insert,
        subscribers_count=incoming_subs,
        topic=incoming_topic or None,
        custom_url=incoming_custom_url or None,
        created_at=created_at,
    )
    update_set: dict = {"updated_at": created_at}
    if incoming_title:
        update_set["title"] = incoming_title
    else:
        update_set["title"] = table.c.title
    if incoming_subs > 0:
        update_set["subscribers_count"] = incoming_subs
    else:
        update_set["subscribers_count"] = table.c.subscribers_count
    if incoming_topic:
        update_set["topic"] = incoming_topic
    else:
        update_set["topic"] = table.c.topic
    if incoming_custom_url:
        update_set["custom_url"] = incoming_custom_url
    else:
        update_set["custom_url"] = table.c.custom_url
    session.execute(
        insert_stmt.on_conflict_do_update(
            index_elements=[Channel.id],
            set_=update_set,
        ),
    )


def persist_discovered_video(
    session: Session,
    video: VideoSearchModel,
    *,
    discovery_keyword: str,
) -> VideoPersistResult:
    """
    Upsert ``Video`` (+ minimal ``Channel``) for monitoring handoff.

    Does not write VideoSnapshot rows. Does not touch ExplosiveChannel.
    """
    video_id = (video.video_id or "").strip()
    channel_id = (video.channel_id or "").strip()
    if not video_id or not channel_id:
        return VideoPersistResult(video_id=video_id or "?", outcome="skipped_invalid")

    content_format = _infer_content_format(video)
    if content_format == VideoFormat.SHORT:
        return VideoPersistResult(video_id=video_id, outcome="skipped_short")
    if content_format == VideoFormat.LIVE:
        return VideoPersistResult(video_id=video_id, outcome="skipped_live")

    published_at = _published_at_from_search(video)
    if published_at is None:
        return VideoPersistResult(video_id=video_id, outcome="skipped_invalid")

    now = utc_now()
    channel_title = (video.channel_title or "").strip()
    _upsert_discovered_channel(
        session,
        channel_id,
        title=channel_title,
        subscribers_count=video.subscribers_count,
        created_at=now,
    )

    views = max(video.views_count, 0)
    duration_seconds = _parse_duration_seconds(video.duration_text)
    title = (video.title or "").strip() or video_id

    existing = session.get(Video, video_id)
    if existing is None:
        session.add(
            Video(
                id=video_id,
                title=title,
                views_count=views,
                likes_count=0,
                comments_count=0,
                published_at=published_at,
                duration_seconds=duration_seconds,
                content_format=content_format,
                topic=discovery_keyword.strip() or None,
                tags=[],
                channel_id=channel_id,
            ),
        )
        return VideoPersistResult(video_id=video_id, outcome="inserted")

    new_title = (video.title or "").strip()
    if new_title:
        existing.title = new_title
    if views > 0:
        existing.views_count = views
    existing.published_at = published_at
    if duration_seconds > 0:
        existing.duration_seconds = duration_seconds
    existing.content_format = content_format
    existing.channel_id = channel_id
    if not (existing.topic or "").strip() and discovery_keyword.strip():
        existing.topic = discovery_keyword.strip()
    return VideoPersistResult(video_id=video_id, outcome="updated")
