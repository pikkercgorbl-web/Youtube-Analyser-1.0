"""Batch upsert for discovered videos in one discovery keyword (Stage 1.20E.6)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.youtube.client import VideoSearchModel
from app.models.orm import Video
from app.services.discovered_video_persistence import (
    VideoPersistResult,
    persist_discovered_video,
)


def batch_persist_discovered_videos(
    session: Session,
    videos: list[VideoSearchModel],
    *,
    discovery_keyword: str,
    cycle_persisted_ids: set[str],
) -> tuple[list[VideoPersistResult], int]:
    """
    Persist unique regular videos for one keyword.

    Uses one ``SELECT`` for existing rows instead of per-video ``session.get``.
    Skips videos already persisted earlier in the same cycle (``cycle_persisted_ids``).
    """
    results: list[VideoPersistResult] = []
    duplicate_occurrences = 0
    to_persist: list[VideoSearchModel] = []
    for video in videos:
        vid = (video.video_id or "").strip()
        if not vid:
            continue
        if vid in cycle_persisted_ids:
            duplicate_occurrences += 1
            continue
        to_persist.append(video)

    if not to_persist:
        return results, duplicate_occurrences

    ids = [(v.video_id or "").strip() for v in to_persist]
    ids = [i for i in ids if i]
    existing_map: dict[str, Video] = {}
    if ids:
        chunk_size = 400
        for start in range(0, len(ids), chunk_size):
            chunk = ids[start : start + chunk_size]
            for row in session.scalars(select(Video).where(Video.id.in_(chunk))).all():
                existing_map[row.id] = row

    for video in to_persist:
        vid = (video.video_id or "").strip()
        if vid in cycle_persisted_ids:
            duplicate_occurrences += 1
            continue
        if vid in existing_map:
            existing_arg: Video | None = existing_map[vid]
        else:
            existing_arg = None
        outcome = persist_discovered_video(
            session,
            video,
            discovery_keyword=discovery_keyword,
            existing_video=existing_arg,
        )
        results.append(outcome)
        if outcome.outcome in ("inserted", "updated"):
            cycle_persisted_ids.add(vid)

    return results, duplicate_occurrences
