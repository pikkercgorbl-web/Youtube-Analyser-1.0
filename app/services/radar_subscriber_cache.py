"""Subscriber cache helpers for radar qualification (Stage 1.20E.6)."""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import Channel


def prefill_subscriber_cache_from_db(
    session: Session,
    channel_ids: Iterable[str],
    cache: dict[str, int | None],
) -> None:
    """Fill ``cache`` from ``Channel.subscribers_count`` without network I/O."""
    missing = [cid.strip() for cid in channel_ids if cid.strip() and cid.strip() not in cache]
    if not missing:
        return
    unique = list(dict.fromkeys(missing))
    chunk_size = 400
    for start in range(0, len(unique), chunk_size):
        chunk = unique[start : start + chunk_size]
        for row in session.scalars(select(Channel).where(Channel.id.in_(chunk))).all():
            subs = max(int(row.subscribers_count or 0), 0)
            if subs > 0:
                cache.setdefault(row.id, subs)
