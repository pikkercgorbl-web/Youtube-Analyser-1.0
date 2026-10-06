"""Candidate selection for Radar enrichment pass (Stage 2.5)."""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, exists, not_, or_, select
from sqlalchemy.orm import Session

from app.models.orm import (
    Channel,
    ChannelSubscriberEnrichmentAttempt,
    KeywordDiscoveryHit,
    Video,
    VideoFormat,
    VideoFormatEnrichmentAttempt,
)
from app.services.channel_subscriber_enrichment import attempt_subscriber_fetch_due
from app.services.format_enrichment_attempts import (
    FORMAT_ENRICHMENT_RETRY_OUTCOMES,
    format_enrichment_retry_due,
)
from app.services.channel_subscriber_backfill import (
    SUBSCRIBERS_API_FAILED,
    SUBSCRIBERS_API_HIDDEN,
    SUBSCRIBERS_API_KNOWN,
    SUBSCRIBERS_API_MISSING,
)
from app.services.metrics import ensure_utc, utc_now
from app.services.radar_enrichment_config import RadarEnrichmentSettings, radar_enrichment_settings
from app.services.radar_target_eligibility import RADAR_MAX_CHANNEL_SUBSCRIBERS, resolve_known_subscribers
from app.services.video_format_batch_apply import video_needs_format_enrichment
from app.services.video_format_api_verification import load_api_format_confirmed_video_ids
from app.services.video_format_outcomes import OUTCOME_CONFIRMED_REGULAR


@dataclass(frozen=True, slots=True)
class RadarEnrichmentPassContext:
    discovery_run_id: str | None = None
    cycle_video_ids: frozenset[str] = frozenset()
    cycle_channel_ids: frozenset[str] = frozenset()
    pass_sequence: int = 0
    fetched_channel_ids: frozenset[str] = frozenset()
    fetched_video_ids: frozenset[str] = frozenset()


def _channel_subscriber_fetch_due(
    channel: Channel,
    *,
    now: datetime,
    settings: RadarEnrichmentSettings,
) -> bool:
    status = channel.subscribers_api_status
    checked = channel.subscribers_api_checked_at
    if status is None:
        return True
    if status == SUBSCRIBERS_API_KNOWN:
        if settings.subscriber_known_recheck_days <= 0:
            return False
        if checked is None:
            return True
        return ensure_utc(checked) <= now - timedelta(days=settings.subscriber_known_recheck_days)
    if status == SUBSCRIBERS_API_HIDDEN:
        if checked is None:
            return False
        return ensure_utc(checked) <= now - timedelta(hours=settings.subscriber_hidden_cooldown_hours)
    if status in (SUBSCRIBERS_API_FAILED, SUBSCRIBERS_API_MISSING):
        if checked is None:
            return True
        return ensure_utc(checked) <= now - timedelta(hours=settings.subscriber_retry_after_hours)
    return True


def _channel_priority(
    channel_id: str,
    *,
    context: RadarEnrichmentPassContext,
    recent_channel_ids: set[str],
    pass_sequence: int,
) -> tuple:
    if channel_id in context.cycle_channel_ids:
        band = 0
    elif channel_id in recent_channel_ids:
        band = 1
    else:
        band = 2
    tie = (zlib.crc32(channel_id.encode("utf-8")) ^ pass_sequence) if band == 2 else 0
    return (band, tie)


def select_subscriber_enrichment_channel_ids(
    session: Session,
    *,
    limit: int,
    context: RadarEnrichmentPassContext,
    settings: RadarEnrichmentSettings | None = None,
    now: datetime | None = None,
) -> list[str]:
    cfg = settings or radar_enrichment_settings
    reference = ensure_utc(now or utc_now())
    if limit <= 0:
        return []

    recent_cutoff = reference - timedelta(hours=cfg.format_recent_hit_hours)
    recent_channel_ids = set(
        session.scalars(
            select(Video.channel_id)
            .join(KeywordDiscoveryHit, KeywordDiscoveryHit.video_id == Video.id)
            .where(
                KeywordDiscoveryHit.discovered_at >= recent_cutoff,
                Video.channel_id.is_not(None),
            )
            .distinct(),
        ).all(),
    )

    exclude = set(context.fetched_channel_ids)
    stmt = select(Channel).order_by(Channel.updated_at.desc()).limit(max(limit * 20, 500))
    candidates: list[tuple[tuple, str]] = []
    seen: set[str] = set()
    for channel in session.scalars(stmt).all():
        if channel.id in exclude:
            continue
        if not _channel_subscriber_fetch_due(channel, now=reference, settings=cfg):
            continue
        key = _channel_priority(channel.id, context=context, recent_channel_ids=recent_channel_ids, pass_sequence=context.pass_sequence)
        candidates.append((key, channel.id))
        seen.add(channel.id)

    orphan_ids = session.scalars(
        select(Video.channel_id)
        .distinct()
        .where(
            Video.channel_id.is_not(None),
            ~Video.channel_id.in_(select(Channel.id)),
        )
        .limit(max(limit * 10, 200)),
    ).all()
    if orphan_ids:
        attempts = {
            row.channel_id: row
            for row in session.scalars(
                select(ChannelSubscriberEnrichmentAttempt).where(
                    ChannelSubscriberEnrichmentAttempt.channel_id.in_(orphan_ids),
                ),
            ).all()
        }
        for cid in orphan_ids:
            if not cid or cid in exclude or cid in seen:
                continue
            attempt = attempts.get(cid)
            if attempt is not None and not attempt_subscriber_fetch_due(attempt, now=reference, settings=cfg):
                continue
            key = _channel_priority(
                cid,
                context=context,
                recent_channel_ids=recent_channel_ids,
                pass_sequence=context.pass_sequence,
            )
            candidates.append((key, cid))
            seen.add(cid)

    candidates.sort(key=lambda item: item[0])
    out: list[str] = []
    for _, cid in candidates:
        out.append(cid)
        if len(out) >= limit:
            break
    return out


def _format_priority(
    video: Video,
    *,
    context: RadarEnrichmentPassContext,
    views_at_discovery: int | None,
    recent_video_ids: set[str],
    pass_sequence: int,
) -> tuple:
    if video.id in context.cycle_video_ids:
        band = 0
    elif video.id in recent_video_ids:
        band = 1
    else:
        band = 2
    views = int(views_at_discovery or video.views_count or 0)
    published_ts = ensure_utc(video.published_at).timestamp() if video.published_at else 0.0
    tie = (zlib.crc32(video.id.encode("utf-8")) ^ pass_sequence) if band == 2 else 0
    return (band, tie, -views, -published_ts)


_FORMAT_SELECTION_PAGE_SIZE = 1000


def _format_selection_sort_key(
    video: Video,
    *,
    context: RadarEnrichmentPassContext,
    priority_channel_ids: frozenset[str],
    views_at_discovery: int | None,
    recent_video_ids: set[str],
    pass_sequence: int,
) -> tuple:
    pass_channel_band = (
        0
        if priority_channel_ids and video.channel_id and video.channel_id in priority_channel_ids
        else 1
    )
    fmt_key = _format_priority(
        video,
        context=context,
        views_at_discovery=views_at_discovery,
        recent_video_ids=recent_video_ids,
        pass_sequence=pass_sequence,
    )
    return (pass_channel_band, *fmt_key)


def select_format_enrichment_video_ids(
    session: Session,
    *,
    limit: int,
    context: RadarEnrichmentPassContext,
    priority_channel_ids: frozenset[str] | None = None,
    settings: RadarEnrichmentSettings | None = None,
    now: datetime | None = None,
    selection_profile: dict[str, int] | None = None,
) -> list[str]:
    """
    Eligible format candidates: SQL prefilter + keyset scan, then priority sort and limit.

    priority_channel_ids boosts videos on subscriber-pass channels; global backlog fills the batch.
    """
    cfg = settings or radar_enrichment_settings
    reference = ensure_utc(now or utc_now())
    if limit <= 0:
        return []

    priority_channels = priority_channel_ids or frozenset()
    exclude = set(context.fetched_video_ids)
    recent_cutoff = reference - timedelta(hours=cfg.format_recent_hit_hours)
    retry_cutoff = reference - timedelta(hours=cfg.format_enrichment_retry_after_hours)

    hit_rows = session.execute(
        select(
            KeywordDiscoveryHit.video_id,
            KeywordDiscoveryHit.views_at_discovery,
        ).where(KeywordDiscoveryHit.discovered_at >= recent_cutoff),
    ).all()
    recent_video_ids = {row.video_id for row in hit_rows}
    views_by_video = {row.video_id: row.views_at_discovery for row in hit_rows}

    confirmed_exists = (
        exists(
            select(VideoFormatEnrichmentAttempt.video_id).where(
                VideoFormatEnrichmentAttempt.video_id == Video.id,
                VideoFormatEnrichmentAttempt.last_outcome == OUTCOME_CONFIRMED_REGULAR,
            ),
        )
        .correlate(Video)
    )
    needs_format_sql = or_(
        Video.content_format == VideoFormat.UNKNOWN,
        and_(
            Video.content_format.in_((VideoFormat.MEDIUM, VideoFormat.LONG)),
            not_(confirmed_exists),
        ),
    )
    known_subs_channel = and_(
        Channel.subscribers_api_status == SUBSCRIBERS_API_KNOWN,
        Channel.subscribers_count <= RADAR_MAX_CHANNEL_SUBSCRIBERS,
    )
    retry_due_sql = or_(
        VideoFormatEnrichmentAttempt.video_id.is_(None),
        VideoFormatEnrichmentAttempt.last_outcome.notin_(tuple(FORMAT_ENRICHMENT_RETRY_OUTCOMES)),
        VideoFormatEnrichmentAttempt.last_attempt_at <= retry_cutoff,
    )

    pages = 0
    rows_scanned = 0
    candidates: list[tuple[tuple, str]] = []
    cursor_id = ""

    while True:
        page_stmt = (
            select(
                Video,
                VideoFormatEnrichmentAttempt.last_outcome,
                VideoFormatEnrichmentAttempt.last_attempt_at,
            )
            .join(Channel, Video.channel_id == Channel.id)
            .outerjoin(
                VideoFormatEnrichmentAttempt,
                VideoFormatEnrichmentAttempt.video_id == Video.id,
            )
            .where(Video.content_format.not_in((VideoFormat.SHORT, VideoFormat.LIVE)))
            .where(needs_format_sql)
            .where(known_subs_channel)
            .where(retry_due_sql)
            .where(Video.id > cursor_id)
            .order_by(Video.id)
            .limit(_FORMAT_SELECTION_PAGE_SIZE)
        )
        rows = session.execute(page_stmt).all()
        if not rows:
            break
        pages += 1
        rows_scanned += len(rows)
        cursor_id = rows[-1][0].id

        batch_ids = [video.id for video, _, _ in rows]
        confirmed = load_api_format_confirmed_video_ids(session, batch_ids)

        for video, last_outcome, last_attempt_at in rows:
            if video.id in exclude:
                continue
            if not video_needs_format_enrichment(
                content_format=video.content_format,
                video_id=video.id,
                confirmed_regular_ids=confirmed,
                last_outcome=last_outcome,
            ):
                continue
            if not format_enrichment_retry_due(
                last_outcome=last_outcome,
                last_attempt_at=last_attempt_at,
                now=reference,
                retry_after_hours=cfg.format_enrichment_retry_after_hours,
            ):
                continue
            key = _format_selection_sort_key(
                video,
                context=context,
                priority_channel_ids=priority_channels,
                views_at_discovery=views_by_video.get(video.id),
                recent_video_ids=recent_video_ids,
                pass_sequence=context.pass_sequence,
            )
            candidates.append((key, video.id))

    candidates.sort(key=lambda item: item[0])
    out: list[str] = []
    for _, vid in candidates:
        out.append(vid)
        if len(out) >= limit:
            break

    if selection_profile is not None:
        selection_profile.clear()
        selection_profile.update(
            {
                "pages_scanned": pages,
                "rows_scanned": rows_scanned,
                "eligible_before_limit": len(candidates),
            },
        )
    return out


def channels_with_known_subs_at_most(
    session: Session,
    channel_ids: set[str],
    *,
    max_subscribers: int = RADAR_MAX_CHANNEL_SUBSCRIBERS,
) -> frozenset[str]:
    if not channel_ids:
        return frozenset()
    eligible: set[str] = set()
    ids = list(channel_ids)
    for start in range(0, len(ids), 400):
        chunk = ids[start : start + 400]
        for ch in session.scalars(select(Channel).where(Channel.id.in_(chunk))).all():
            subs = resolve_known_subscribers(channel=ch, latest_snapshot=None)
            if subs is not None and subs <= max_subscribers:
                eligible.add(ch.id)
    return frozenset(eligible)


def diagnose_format_enrichment_selection(
    session: Session,
    *,
    channel_ids: set[str],
    context: RadarEnrichmentPassContext,
    settings: RadarEnrichmentSettings | None = None,
    now: datetime | None = None,
    sample_limit: int = 500,
) -> dict[str, object]:
    """Count linked videos and rejection reasons after subscriber updates in the same pass."""
    cfg = settings or radar_enrichment_settings
    reference = ensure_utc(now or utc_now())
    if not channel_ids:
        return {"linked_videos": 0, "rejections": {}, "selected_would_be": 0}

    rejections: dict[str, int] = {}
    linked = 0
    would_select = 0

    recent_cutoff = reference - timedelta(hours=cfg.format_recent_hit_hours)
    hit_rows = session.execute(
        select(
            KeywordDiscoveryHit.video_id,
            KeywordDiscoveryHit.views_at_discovery,
        ).where(KeywordDiscoveryHit.discovered_at >= recent_cutoff),
    ).all()
    recent_video_ids = {row.video_id for row in hit_rows}
    views_by_video = {row.video_id: row.views_at_discovery for row in hit_rows}

    channels_by_id: dict[str, Channel] = {}
    ids = list(channel_ids)
    for start in range(0, len(ids), 400):
        chunk = ids[start : start + 400]
        for ch in session.scalars(select(Channel).where(Channel.id.in_(chunk))).all():
            channels_by_id[ch.id] = ch

    stmt = (
        select(
            Video,
            VideoFormatEnrichmentAttempt.last_outcome,
            VideoFormatEnrichmentAttempt.last_attempt_at,
        )
        .outerjoin(
            VideoFormatEnrichmentAttempt,
            VideoFormatEnrichmentAttempt.video_id == Video.id,
        )
        .where(Video.channel_id.in_(ids))
        .limit(sample_limit)
    )
    rows = session.execute(stmt).all()
    video_ids = [video.id for video, _, _ in rows]
    confirmed = load_api_format_confirmed_video_ids(session, video_ids)

    for video, last_outcome, last_attempt_at in rows:
        linked += 1
        if video.id in context.fetched_video_ids:
            rejections["already_fetched_in_pass"] = rejections.get("already_fetched_in_pass", 0) + 1
            continue
        if not video_needs_format_enrichment(
            content_format=video.content_format,
            video_id=video.id,
            confirmed_regular_ids=confirmed,
            last_outcome=last_outcome,
        ):
            rejections["format_not_needed"] = rejections.get("format_not_needed", 0) + 1
            continue
        channel = channels_by_id.get(video.channel_id) if video.channel_id else None
        subs = resolve_known_subscribers(channel=channel, latest_snapshot=None)
        if subs is None:
            rejections["unknown_subscribers"] = rejections.get("unknown_subscribers", 0) + 1
            continue
        if subs > RADAR_MAX_CHANNEL_SUBSCRIBERS:
            rejections["subscribers_over_cap"] = rejections.get("subscribers_over_cap", 0) + 1
            continue
        if not format_enrichment_retry_due(
            last_outcome=last_outcome,
            last_attempt_at=last_attempt_at,
            now=reference,
            retry_after_hours=cfg.format_enrichment_retry_after_hours,
        ):
            rejections["format_retry_cooldown"] = rejections.get("format_retry_cooldown", 0) + 1
            continue
        would_select += 1

    return {
        "linked_videos": linked,
        "rejections": rejections,
        "selected_would_be": would_select,
        "channels_with_row": len(channels_by_id),
        "recent_hit_videos_in_sample": sum(
            1 for video, _, _ in rows if video.id in recent_video_ids
        ),
        "views_by_video_sample_size": len(views_by_video),
    }
