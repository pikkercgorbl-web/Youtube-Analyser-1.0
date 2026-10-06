"""Load existing Radar evidence for one Attention refresh (no YouTube HTTP)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import Channel, ChannelSnapshot, KeywordDiscoveryHit, TargetKeyword, Video, VideoFormat, VideoSnapshot
from app.services.breakout_ranking_service import breakout_fundamental_eligibility, rank_breakout_v1
from app.services.metrics import ensure_utc
from app.services.monitoring_tier_budget_policy import DEFAULT_MAX_AGE_MONITORING_HOURS
from app.services.monitoring_video_source import MonitoredVideoState, _state_from_video
from app.services.video_snapshot_storage import get_latest_snapshots_for_videos, get_snapshots_for_videos

_IN_CHUNK = 400


def _chunked_in(ids: list[str] | list[int], chunk_size: int = _IN_CHUNK):
    for start in range(0, len(ids), chunk_size):
        yield ids[start : start + chunk_size]


@dataclass
class AttentionVideoRecord:
    video: Video
    channel: Channel | None
    latest_snapshot: VideoSnapshot | None
    snapshots: list[VideoSnapshot]
    hits: list[KeywordDiscoveryHit]
    state: MonitoredVideoState
    breakout_eligible: bool
    breakout_rank: int | None
    subscribers: int | None
    views: int | None
    vph: float | None


@dataclass
class AttentionEvidenceBundle:
    window_start: datetime
    window_end: datetime
    records: dict[str, AttentionVideoRecord]
    hits_by_video: dict[str, list[KeywordDiscoveryHit]]
    hits_by_keyword: dict[int, list[KeywordDiscoveryHit]]
    keyword_text: dict[int, str]
    channel_snapshots: dict[str, list[ChannelSnapshot]]
    extra_channel_videos: dict[str, list[Video]]
    extra_video_states: dict[str, MonitoredVideoState]
    extra_latest_snapshots: dict[str, VideoSnapshot]
    extra_hits_by_video: dict[str, list[KeywordDiscoveryHit]]
    extra_snapshots_by_video: dict[str, list[VideoSnapshot]] = field(default_factory=dict)


def resolve_subscribers(
    *,
    channel: Channel | None,
    latest_snapshot: VideoSnapshot | None,
) -> int | None:
    """Missing subscriber observations stay None. Stored 0 on Channel is not treated as known."""
    if latest_snapshot is not None and latest_snapshot.subscribers is not None:
        return int(latest_snapshot.subscribers)
    if channel is None:
        return None
    if channel.subscribers_count and channel.subscribers_count > 0:
        return int(channel.subscribers_count)
    return None


def load_candidate_video_ids(
    session: Session,
    *,
    window_start: datetime,
    window_end: datetime,
) -> list[str]:
    start = ensure_utc(window_start)
    end = ensure_utc(window_end)
    hit_ids = session.scalars(
        select(KeywordDiscoveryHit.video_id).where(
            KeywordDiscoveryHit.discovered_at >= start,
            KeywordDiscoveryHit.discovered_at <= end,
        ),
    ).all()
    published_ids = session.scalars(
        select(Video.id).where(
            Video.published_at >= start,
            Video.published_at <= end,
            Video.content_format.not_in((VideoFormat.SHORT, VideoFormat.LIVE)),
        ),
    ).all()
    return list(dict.fromkeys([*hit_ids, *published_ids]))


def load_attention_evidence(
    session: Session,
    *,
    window_start: datetime,
    window_end: datetime,
    channel_lookback_start: datetime,
) -> AttentionEvidenceBundle:
    start = ensure_utc(window_start)
    end = ensure_utc(window_end)
    lookback = ensure_utc(channel_lookback_start)
    candidate_ids = load_candidate_video_ids(session, window_start=start, window_end=end)
    candidate_videos: list[Video] = []
    for chunk in _chunked_in(candidate_ids) if candidate_ids else []:
        candidate_videos.extend(session.scalars(select(Video).where(Video.id.in_(chunk))).all())
    window_channel_ids = list({row.channel_id for row in candidate_videos if row.channel_id})
    extra_ids: list[str] = []
    for chunk in _chunked_in(window_channel_ids) if window_channel_ids else []:
        extra_ids.extend(
            session.scalars(
                select(Video.id).where(
                    Video.channel_id.in_(chunk),
                    Video.published_at >= lookback,
                    Video.published_at <= end,
                    Video.content_format.not_in((VideoFormat.SHORT, VideoFormat.LIVE)),
                ),
            ).all(),
        )
    all_ids = list(dict.fromkeys([*candidate_ids, *extra_ids]))
    videos: list[Video] = []
    loaded_ids = {row.id for row in candidate_videos}
    videos.extend(candidate_videos)
    remaining = [vid for vid in all_ids if vid not in loaded_ids]
    for chunk in _chunked_in(remaining) if remaining else []:
        videos.extend(session.scalars(select(Video).where(Video.id.in_(chunk))).all())
    channel_ids = list({row.channel_id for row in videos if row.channel_id})
    channels: list[Channel] = []
    for chunk in _chunked_in(channel_ids) if channel_ids else []:
        channels.extend(session.scalars(select(Channel).where(Channel.id.in_(chunk))).all())
    channel_by_id = {row.id: row for row in channels}

    latest = get_latest_snapshots_for_videos(session, all_ids)
    histories: list[VideoSnapshot] = []
    for chunk in _chunked_in(candidate_ids) if candidate_ids else []:
        histories.extend(get_snapshots_for_videos(session, chunk))
    snaps_by_video: dict[str, list[VideoSnapshot]] = defaultdict(list)
    for snap in histories:
        snaps_by_video[snap.video_id].append(snap)

    hits: list[KeywordDiscoveryHit] = []
    for chunk in _chunked_in(all_ids) if all_ids else []:
        hits.extend(
            session.scalars(select(KeywordDiscoveryHit).where(KeywordDiscoveryHit.video_id.in_(chunk))).all(),
        )
    hits_by_video: dict[str, list[KeywordDiscoveryHit]] = defaultdict(list)
    hits_by_keyword: dict[int, list[KeywordDiscoveryHit]] = defaultdict(list)
    for hit in hits:
        hits_by_video[hit.video_id].append(hit)
        hits_by_keyword[hit.keyword_id].append(hit)

    keyword_ids = list(hits_by_keyword)
    keyword_text: dict[int, str] = {}
    for chunk in _chunked_in(keyword_ids) if keyword_ids else []:
        for row in session.scalars(select(TargetKeyword).where(TargetKeyword.id.in_(chunk))).all():
            keyword_text[row.id] = row.keyword

    window_records: dict[str, AttentionVideoRecord] = {}
    extra_states: dict[str, MonitoredVideoState] = {}
    extra_videos_by_channel: dict[str, list[Video]] = defaultdict(list)
    extra_latest: dict[str, VideoSnapshot] = {}

    for video in videos:
        latest_snap = latest.get(video.id)
        state = _state_from_video(video, now=end, latest_snapshot=latest_snap)
        extra_videos_by_channel[video.channel_id].append(video)
        extra_states[video.id] = state
        if latest_snap is not None:
            extra_latest[video.id] = latest_snap
        if video.id not in candidate_ids:
            continue
        eligible, _ = breakout_fundamental_eligibility(
            state,
            max_age_monitoring_hours=DEFAULT_MAX_AGE_MONITORING_HOURS,
        )
        channel = channel_by_id.get(video.channel_id)
        views = (
            latest_snap.views
            if latest_snap is not None and latest_snap.views is not None
            else video.views_count
        )
        window_records[video.id] = AttentionVideoRecord(
            video=video,
            channel=channel,
            latest_snapshot=latest_snap,
            snapshots=sorted(snaps_by_video.get(video.id, []), key=lambda s: ensure_utc(s.captured_at)),
            hits=hits_by_video.get(video.id, []),
            state=state,
            breakout_eligible=eligible,
            breakout_rank=None,
            subscribers=resolve_subscribers(channel=channel, latest_snapshot=latest_snap),
            views=int(views) if views is not None else None,
            vph=state.raw_vph,
        )

    ranked = rank_breakout_v1(
        [rec.state for rec in window_records.values()],
        views_by_video_id={vid: rec.views for vid, rec in window_records.items()},
    )
    rank_by_id = {row.video_id: row.rank for row in ranked}
    for vid, rec in window_records.items():
        rec.breakout_rank = rank_by_id.get(vid)

    channel_snaps: dict[str, list[ChannelSnapshot]] = defaultdict(list)
    for chunk in _chunked_in(channel_ids) if channel_ids else []:
        for row in session.scalars(
            select(ChannelSnapshot)
            .where(ChannelSnapshot.channel_id.in_(chunk))
            .order_by(ChannelSnapshot.recorded_at.asc()),
        ).all():
            channel_snaps[row.channel_id].append(row)

    extra_snaps: list[VideoSnapshot] = []
    extra_history_ids = [vid for vid in extra_ids if vid not in set(candidate_ids)]
    for chunk in _chunked_in(extra_history_ids) if extra_history_ids else []:
        extra_snaps.extend(get_snapshots_for_videos(session, chunk))
    extra_by_video: dict[str, list[VideoSnapshot]] = defaultdict(list)
    for vid, rows in snaps_by_video.items():
        extra_by_video[vid].extend(rows)
    for snap in extra_snaps:
        extra_by_video[snap.video_id].append(snap)

    return AttentionEvidenceBundle(
        window_start=start,
        window_end=end,
        records=window_records,
        hits_by_video=dict(hits_by_video),
        hits_by_keyword=dict(hits_by_keyword),
        keyword_text=keyword_text,
        channel_snapshots=dict(channel_snaps),
        extra_channel_videos=dict(extra_videos_by_channel),
        extra_video_states=extra_states,
        extra_latest_snapshots=extra_latest,
        extra_hits_by_video=dict(hits_by_video),
        extra_snapshots_by_video=dict(extra_by_video),
    )
