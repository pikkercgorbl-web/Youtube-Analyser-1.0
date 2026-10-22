"""Shared discovery-cycle batch for SavedVideo similar + SavedFamily topic watches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import (
    SavedFamily,
    SavedFamilyTopicWatch,
    SavedVideo,
    SavedVideoSimilarWatch,
)
from app.services.metrics import ensure_utc, utc_now
from app.services.saved_family_topic_watch import execute_family_topic_watch_scan
from app.services.saved_video_similar_watch import (
    WATCH_ACTIVE,
    SimilarWatchScanInProgressError,
    execute_similar_watch_scan,
    _load_queries as load_video_queries,
)
from app.services.saved_family_topic_watch import _load_queries as load_family_queries
from app.services.saved_video_similar_watch_config import saved_video_similar_watch_settings

WatchKind = Literal["video", "family"]


@dataclass(order=True, slots=True)
class _DueWatch:
    sort_key: datetime
    kind: WatchKind
    entity_id: int
    batch_query_offset: int


def count_active_library_watches(session: Session) -> int:
    video_count = int(
        session.scalar(
            select(func.count())
            .select_from(SavedVideoSimilarWatch)
            .join(SavedVideo, SavedVideo.id == SavedVideoSimilarWatch.saved_video_id)
            .where(
                SavedVideoSimilarWatch.status == WATCH_ACTIVE,
                SavedVideo.archived_at.is_(None),
            ),
        )
        or 0,
    )
    family_count = int(
        session.scalar(
            select(func.count())
            .select_from(SavedFamilyTopicWatch)
            .join(SavedFamily, SavedFamily.id == SavedFamilyTopicWatch.saved_family_id)
            .where(
                SavedFamilyTopicWatch.status == WATCH_ACTIVE,
                SavedFamily.archived_at.is_(None),
            ),
        )
        or 0,
    )
    return video_count + family_count


def run_library_watch_batch_for_discovery_cycle(session: Session) -> int:
    """Process due video + family watches fairly; returns number of watches scanned."""
    cfg = saved_video_similar_watch_settings
    now = utc_now()
    due_entries: list[_DueWatch] = []

    video_rows = session.scalars(
        select(SavedVideoSimilarWatch)
        .join(SavedVideo, SavedVideo.id == SavedVideoSimilarWatch.saved_video_id)
        .where(
            SavedVideoSimilarWatch.status == WATCH_ACTIVE,
            SavedVideo.archived_at.is_(None),
            SavedVideoSimilarWatch.next_scan_at.is_not(None),
            SavedVideoSimilarWatch.next_scan_at <= now,
        ),
    ).all()
    for watch in video_rows:
        due_entries.append(
            _DueWatch(
                sort_key=ensure_utc(watch.next_scan_at),
                kind="video",
                entity_id=watch.saved_video_id,
                batch_query_offset=max(0, int(watch.batch_query_offset or 0)),
            ),
        )

    family_rows = session.scalars(
        select(SavedFamilyTopicWatch)
        .join(SavedFamily, SavedFamily.id == SavedFamilyTopicWatch.saved_family_id)
        .where(
            SavedFamilyTopicWatch.status == WATCH_ACTIVE,
            SavedFamily.archived_at.is_(None),
            SavedFamilyTopicWatch.next_scan_at.is_not(None),
            SavedFamilyTopicWatch.next_scan_at <= now,
        ),
    ).all()
    for watch in family_rows:
        due_entries.append(
            _DueWatch(
                sort_key=ensure_utc(watch.next_scan_at),
                kind="family",
                entity_id=watch.saved_family_id,
                batch_query_offset=max(0, int(watch.batch_query_offset or 0)),
            ),
        )

    due_entries.sort()
    candidates = due_entries[: cfg.max_watches_per_cycle]

    scanned = 0
    query_budget = cfg.max_query_searches_per_cycle
    for entry in candidates:
        if query_budget <= 0:
            break
        if entry.kind == "video":
            watch = session.get(SavedVideoSimilarWatch, entry.entity_id)
            if watch is None or watch.status != WATCH_ACTIVE:
                continue
            all_queries = load_video_queries(watch)
        else:
            watch = session.get(SavedFamilyTopicWatch, entry.entity_id)
            if watch is None or watch.status != WATCH_ACTIVE:
                continue
            all_queries = load_family_queries(watch)
        if not all_queries:
            continue
        offset = entry.batch_query_offset
        if offset >= len(all_queries):
            offset = 0
        remaining = all_queries[offset:]
        chunk = remaining[:query_budget]
        if not chunk:
            continue
        cycle_complete = offset + len(chunk) >= len(all_queries)
        try:
            if entry.kind == "video":
                execute_similar_watch_scan(
                    session,
                    saved_video_id=entry.entity_id,
                    trigger="scheduled",
                    queries_to_run=chunk,
                    batch_query_cycle_complete=cycle_complete,
                )
                watch = session.get(SavedVideoSimilarWatch, entry.entity_id)
            else:
                execute_family_topic_watch_scan(
                    session,
                    saved_family_id=entry.entity_id,
                    trigger="scheduled",
                    queries_to_run=chunk,
                    batch_query_cycle_complete=cycle_complete,
                )
                watch = session.get(SavedFamilyTopicWatch, entry.entity_id)
            if watch is not None:
                watch.batch_query_offset = 0 if cycle_complete else offset + len(chunk)
            query_budget -= len(chunk)
            scanned += 1
        except SimilarWatchScanInProgressError:
            continue
        except Exception:
            continue
    return scanned
