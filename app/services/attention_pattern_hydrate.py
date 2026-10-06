"""Read-path hydration of pattern member videos from existing Video/snapshot rows.

Does not run Attention Engine, Breakout ranking, Discovery, or YouTube HTTP.
Winner overlay copies persisted VideoWinner fields when the video is in the snapshot top.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import Channel, TargetKeyword, Video
from app.services.attention_engine_types import (
    PatternCandidate,
    VideoWinner,
    youtube_watch_url,
)
from app.services.attention_evidence import resolve_subscribers
from app.services.metrics import ensure_utc
from app.services.video_snapshot_storage import get_latest_snapshots_for_videos

_IN_CHUNK = 400


def _chunked(ids: list[str] | list[int], chunk_size: int = _IN_CHUNK):
    for start in range(0, len(ids), chunk_size):
        yield ids[start : start + chunk_size]


def _age_hours(*, published_at: datetime | None, reference: datetime | None, snapshot_age: float | None) -> float | None:
    if snapshot_age is not None:
        return float(snapshot_age)
    if published_at is None or reference is None:
        return None
    published = ensure_utc(published_at)
    now = ensure_utc(reference)
    if now <= published:
        return None
    hours = (now - published).total_seconds() / 3600.0
    if hours <= 0:
        return None
    return round(hours, 4)


def hydrate_pattern_member_videos(
    session: Session,
    pattern: PatternCandidate,
    winners: tuple[VideoWinner, ...] | list[VideoWinner],
    *,
    computed_at: datetime | None,
) -> list[dict]:
    extra_channels = list(pattern.participating_channel_ids)
    return hydrate_videos_by_ids(
        session,
        list(pattern.participating_video_ids),
        winners,
        computed_at=computed_at,
        extra_channel_ids=extra_channels,
    )


def hydrate_videos_by_ids(
    session: Session,
    video_ids: list[str],
    winners: tuple[VideoWinner, ...] | list[VideoWinner],
    *,
    computed_at: datetime | None,
    extra_channel_ids: list[str] | None = None,
) -> list[dict]:
    video_ids = list(dict.fromkeys(video_ids))
    winner_by_id = {row.video_id: row for row in winners}
    videos: dict[str, Video] = {}
    for chunk in _chunked(video_ids):
        if not chunk:
            continue
        for row in session.scalars(select(Video).where(Video.id.in_(chunk))).all():
            videos[row.id] = row
    channel_ids = list(dict.fromkeys(v.channel_id for v in videos.values() if v.channel_id))
    for cid in extra_channel_ids or []:
        if cid not in channel_ids:
            channel_ids.append(cid)
    channels: dict[str, Channel] = {}
    for chunk in _chunked(channel_ids):
        if not chunk:
            continue
        for row in session.scalars(select(Channel).where(Channel.id.in_(chunk))).all():
            channels[row.id] = row
    snapshots = get_latest_snapshots_for_videos(session, video_ids)

    items: list[dict] = []
    for video_id in video_ids:
        winner = winner_by_id.get(video_id)
        video = videos.get(video_id)
        snap = snapshots.get(video_id)
        channel_id = (
            (winner.channel_id if winner else None)
            or (video.channel_id if video is not None else None)
            or (snap.channel_id if snap is not None else "")
            or ""
        )
        channel = channels.get(channel_id)
        title = (winner.title if winner else None) or (video.title if video is not None else "") or video_id
        channel_title = (
            (winner.channel_title if winner else None)
            or (channel.title if channel is not None else "")
            or channel_id
        )
        published_at = (
            (winner.published_at if winner else None)
            or (video.published_at if video is not None else None)
            or (snap.published_at if snap is not None else None)
        )
        if winner is not None:
            items.append(
                {
                    "video_id": video_id,
                    "title": title,
                    "channel_id": channel_id,
                    "channel_title": channel_title,
                    "youtube_url": winner.youtube_url or youtube_watch_url(video_id),
                    "published_at": published_at,
                    "age_hours": winner.age_hours,
                    "views": winner.views,
                    "vph": winner.vph,
                    "subscribers": winner.subscribers,
                    "in_winner_snapshot": True,
                    "breakout_rank": winner.breakout_rank,
                    "breakout_eligible": winner.breakout_eligible,
                    "acceleration_state": winner.acceleration_state,
                    "delayed_outcome_state": winner.delayed_outcome_state,
                    "delayed_outcome_growth": winner.delayed_outcome_growth,
                    "reason_codes": list(winner.reason_codes),
                    "human_reasons": list(winner.human_reasons),
                    "keyword_ids": list(winner.keyword_ids),
                },
            )
            continue
        views = snap.views if snap is not None else None
        vph = snap.vph if snap is not None else None
        subscribers = resolve_subscribers(channel=channel, latest_snapshot=snap)
        items.append(
            {
                "video_id": video_id,
                "title": title,
                "channel_id": channel_id,
                "channel_title": channel_title,
                "youtube_url": youtube_watch_url(video_id),
                "published_at": published_at,
                "age_hours": _age_hours(
                    published_at=published_at,
                    reference=computed_at,
                    snapshot_age=snap.age_hours if snap is not None else None,
                ),
                "views": views,
                "vph": vph,
                "subscribers": subscribers,
                "in_winner_snapshot": False,
                "breakout_rank": None,
                "breakout_eligible": None,
                "acceleration_state": None,
                "delayed_outcome_state": None,
                "delayed_outcome_growth": None,
                "reason_codes": [],
                "human_reasons": [],
                "keyword_ids": [],
            },
        )
    return items


def hydrate_related_keywords(session: Session, keyword_ids: tuple[int, ...] | list[int]) -> list[dict]:
    ids = list(dict.fromkeys(int(k) for k in keyword_ids))
    if not ids:
        return []
    rows: dict[int, str] = {}
    for chunk in _chunked(ids):
        for row in session.scalars(select(TargetKeyword).where(TargetKeyword.id.in_(chunk))).all():
            rows[row.id] = row.keyword
    return [{"keyword_id": kid, "keyword": rows[kid]} for kid in ids if kid in rows]


def hydrate_participating_channels(
    session: Session,
    channel_ids: tuple[str, ...] | list[str],
    member_videos: list[dict],
) -> list[dict]:
    counts: Counter[str] = Counter()
    titles: dict[str, str] = {}
    for row in member_videos:
        cid = str(row.get("channel_id") or "")
        if not cid:
            continue
        counts[cid] += 1
        titles[cid] = str(row.get("channel_title") or cid)
    missing = [cid for cid in channel_ids if cid not in titles]
    if missing:
        for chunk in _chunked(missing):
            for channel in session.scalars(select(Channel).where(Channel.id.in_(chunk))).all():
                titles[channel.id] = channel.title
                counts.setdefault(channel.id, 0)
    ordered: list[dict] = []
    seen: set[str] = set()
    for cid in channel_ids:
        if cid in seen:
            continue
        seen.add(cid)
        ordered.append(
            {
                "channel_id": cid,
                "channel_title": titles.get(cid) or cid,
                "video_count": int(counts.get(cid, 0)),
            },
        )
    for cid, n in counts.most_common():
        if cid in seen:
            continue
        ordered.append({"channel_id": cid, "channel_title": titles.get(cid) or cid, "video_count": n})
    return ordered
