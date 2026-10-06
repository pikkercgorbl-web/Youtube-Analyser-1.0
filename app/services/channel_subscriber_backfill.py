"""Persist channels.list subscriber counts for Radar eligibility (Stage 2.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.youtube.client import YouTubeChannelDetails
from app.models.orm import Channel
from app.services.metrics import ensure_utc

SUBSCRIBERS_API_KNOWN = "known"
SUBSCRIBERS_API_HIDDEN = "hidden"
SUBSCRIBERS_API_MISSING = "missing"
SUBSCRIBERS_API_FAILED = "failed"
SUBSCRIBERS_API_SOURCE = "channels_list"


class ChannelsListClient(Protocol):
    def get_channels(self, channel_ids: list[str]) -> dict[str, YouTubeChannelDetails]:
        ...


@dataclass
class SubscriberBackfillReport:
    planned_channels: int = 0
    api_batch_count: int = 0
    known: int = 0
    hidden: int = 0
    missing: int = 0
    failed: int = 0
    known_zero: int = 0
    channel_ids_by_status: dict[str, list[str]] = field(default_factory=dict)


def apply_channel_subscriber_details(
    channel: Channel,
    details: YouTubeChannelDetails | None,
    *,
    checked_at: datetime | None = None,
    failed: bool = False,
) -> str:
    stamp = ensure_utc(checked_at or datetime.now(timezone.utc))
    if failed:
        channel.subscribers_api_status = SUBSCRIBERS_API_FAILED
        channel.subscribers_api_checked_at = stamp
        return SUBSCRIBERS_API_FAILED
    if details is None:
        channel.subscribers_api_status = SUBSCRIBERS_API_MISSING
        channel.subscribers_api_checked_at = stamp
        return SUBSCRIBERS_API_MISSING
    if details.subscribers_hidden or not details.subscribers_known:
        channel.subscribers_api_status = SUBSCRIBERS_API_HIDDEN
        channel.subscribers_api_checked_at = stamp
        return SUBSCRIBERS_API_HIDDEN
    count = int(details.subscribers_count or 0)
    channel.subscribers_count = count
    channel.subscribers_api_status = SUBSCRIBERS_API_KNOWN
    channel.subscribers_api_checked_at = stamp
    return SUBSCRIBERS_API_KNOWN


def run_subscriber_backfill(
    session: Session,
    youtube_client: ChannelsListClient,
    channel_ids: list[str],
    *,
    batch_size: int = 50,
) -> SubscriberBackfillReport:
    unique = list(dict.fromkeys(cid for cid in channel_ids if cid))
    report = SubscriberBackfillReport(planned_channels=len(unique))
    for start in range(0, len(unique), batch_size):
        batch = unique[start : start + batch_size]
        report.api_batch_count += 1
        try:
            details_map = youtube_client.get_channels(batch)
        except Exception:
            from app.services.channel_subscriber_enrichment import apply_subscriber_enrichment_batch

            apply_report = apply_subscriber_enrichment_batch(
                session,
                batch,
                {},
                network_failed=True,
            )
            for outcome in apply_report.outcomes:
                status = outcome.api_status or SUBSCRIBERS_API_FAILED
                report.channel_ids_by_status.setdefault(status, []).append(outcome.channel_id)
            report.failed += apply_report.failed
            report.missing += apply_report.missing
            continue

        from app.services.channel_subscriber_enrichment import apply_subscriber_enrichment_batch

        apply_report = apply_subscriber_enrichment_batch(
            session,
            batch,
            details_map,
            network_failed=False,
        )
        for outcome in apply_report.outcomes:
            status = outcome.api_status or SUBSCRIBERS_API_MISSING
            report.channel_ids_by_status.setdefault(status, []).append(outcome.channel_id)
        report.known += apply_report.known
        report.hidden += apply_report.hidden
        report.missing += apply_report.missing
        report.failed += apply_report.failed
        for cid in report.channel_ids_by_status.get(SUBSCRIBERS_API_KNOWN, []):
            row = session.get(Channel, cid)
            if row is not None and int(row.subscribers_count) == 0:
                report.known_zero += 1
    session.flush()
    return report


def select_unknown_subscriber_channel_ids(
    session: Session,
    limit: int = 500,
    *,
    window_start=None,
    window_end=None,
) -> list[str]:
    """Channels from window candidates lacking verified subscribers_api_status=known."""
    from datetime import timedelta

    from app.services.attention_engine_service import attention_window
    from app.services.attention_evidence import load_attention_evidence
    from app.services.metrics import utc_now
    from app.services.radar_target_eligibility import (
        REJECTION_UNKNOWN_SUBSCRIBERS,
        radar_target_rejection_reason,
    )

    end = window_end or utc_now()
    start = window_start or attention_window(now=end, window_hours=24)[0]
    lookback = end - timedelta(days=14)
    bundle = load_attention_evidence(
        session,
        window_start=start,
        window_end=end,
        channel_lookback_start=lookback,
    )
    ordered: list[str] = []
    for rec in bundle.records.values():
        if (
            radar_target_rejection_reason(
                content_format=rec.video.content_format,
                channel=rec.channel,
                latest_snapshot=rec.latest_snapshot,
            )
            != REJECTION_UNKNOWN_SUBSCRIBERS
        ):
            continue
        cid = rec.video.channel_id
        if cid and cid not in ordered:
            ordered.append(cid)
        if len(ordered) >= limit:
            break
    if len(ordered) < limit:
        stmt = (
            select(Channel.id)
            .where(
                (Channel.subscribers_api_status.is_(None))
                | (Channel.subscribers_api_status != SUBSCRIBERS_API_KNOWN),
            )
            .order_by(Channel.updated_at.desc())
            .limit(limit)
        )
        for cid in session.scalars(stmt).all():
            if cid not in ordered:
                ordered.append(cid)
            if len(ordered) >= limit:
                break
    return ordered[:limit]
