"""Explicit offline adapters into snapshot observations (Stage 1.11)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.metrics import ensure_utc
from app.services.video_snapshot_storage import VideoSnapshotObservation


def validation_t0_row_to_observation(
    row: dict[str, Any],
    *,
    source: str = "validation_t0",
    run_id: str = "",
    experiment_id: str | None = None,
) -> VideoSnapshotObservation | None:
    """
    Build a snapshot observation from a serialized validation T0 row.

    Returns None when required timestamps or IDs are missing (no inference).
    """
    video_id = (row.get("video_id") or "").strip()
    channel_id = (row.get("channel_id") or "").strip()
    if not video_id or not channel_id:
        return None

    captured_raw = row.get("discovered_at")
    if not captured_raw:
        return None
    if isinstance(captured_raw, str):
        captured_at = datetime.fromisoformat(captured_raw.replace("Z", "+00:00"))
    elif isinstance(captured_raw, datetime):
        captured_at = captured_raw
    else:
        return None

    published_at: datetime | None = None
    published_raw = row.get("published_at")
    if isinstance(published_raw, str) and published_raw.strip():
        published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
    elif isinstance(published_raw, datetime):
        published_at = published_raw

    views = row.get("discovery_views")
    if views is not None:
        views = int(views)

    subscribers = row.get("final_subscribers")
    if subscribers is None:
        subscribers = row.get("discovery_subscribers")
    if subscribers is not None:
        subscribers = int(subscribers)

    fetch_status = row.get("enrichment_status") or "ok"

    return VideoSnapshotObservation(
        video_id=video_id,
        channel_id=channel_id,
        captured_at=ensure_utc(captured_at),
        source=source,
        run_id=run_id,
        experiment_id=experiment_id,
        keyword=row.get("keyword"),
        published_at=ensure_utc(published_at) if published_at is not None else None,
        views=views,
        subscribers=subscribers if subscribers is not None else None,
        content_format=row.get("content_format"),
        is_short=row.get("is_short"),
        is_live=row.get("is_live"),
        fetch_status=str(fetch_status),
        raw_metadata={"adapter": "validation_t0_row"},
    )
