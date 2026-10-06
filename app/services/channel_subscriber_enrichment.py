"""Batch apply channels.list subscriber enrichment with per-ID outcomes (Stage 2.5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.youtube.client import YouTubeChannelDetails
from app.models.orm import Channel, ChannelSubscriberEnrichmentAttempt
from app.services.channel_subscriber_backfill import (
    SUBSCRIBERS_API_FAILED,
    SUBSCRIBERS_API_HIDDEN,
    SUBSCRIBERS_API_KNOWN,
    SUBSCRIBERS_API_MISSING,
    apply_channel_subscriber_details,
)
from app.services.channel_subscriber_enrichment_attempts import record_channel_subscriber_attempt
from app.services.discovered_video_persistence import upsert_channel_from_youtube_api
from app.services.metrics import ensure_utc
from app.services.radar_enrichment_config import RadarEnrichmentSettings, radar_enrichment_settings

REASON_API_ITEM_EXISTING = "api_item_channel_exists"
REASON_API_ITEM_UPSERTED = "api_item_channel_upserted"
REASON_API_NO_ITEM = "api_no_item"
REASON_NETWORK_FAILED = "network_failed"
REASON_PERSIST_ERROR = "persist_error"


@dataclass
class ChannelSubscriberIdOutcome:
    channel_id: str
    reason: str
    api_status: str | None = None
    retry_after: datetime | None = None


@dataclass
class ChannelSubscriberBatchApplyReport:
    outcomes: list[ChannelSubscriberIdOutcome] = field(default_factory=list)
    known: int = 0
    hidden: int = 0
    missing: int = 0
    failed: int = 0

    def outcome_by_id(self) -> dict[str, ChannelSubscriberIdOutcome]:
        return {o.channel_id: o for o in self.outcomes}


def subscriber_retry_after(
    api_status: str,
    *,
    checked_at: datetime,
    settings: RadarEnrichmentSettings | None = None,
) -> datetime | None:
    cfg = settings or radar_enrichment_settings
    stamp = ensure_utc(checked_at)
    if api_status == SUBSCRIBERS_API_KNOWN:
        if cfg.subscriber_known_recheck_days <= 0:
            return None
        return stamp + timedelta(days=cfg.subscriber_known_recheck_days)
    if api_status == SUBSCRIBERS_API_HIDDEN:
        return stamp + timedelta(hours=cfg.subscriber_hidden_cooldown_hours)
    if api_status in (SUBSCRIBERS_API_FAILED, SUBSCRIBERS_API_MISSING):
        return stamp + timedelta(hours=cfg.subscriber_retry_after_hours)
    return None


def _load_channels(session: Session, channel_ids: list[str]) -> dict[str, Channel]:
    if not channel_ids:
        return {}
    rows = session.scalars(select(Channel).where(Channel.id.in_(channel_ids))).all()
    return {row.id: row for row in rows}


def apply_subscriber_enrichment_batch(
    session: Session,
    batch_ids: list[str],
    details_map: dict[str, YouTubeChannelDetails],
    *,
    network_failed: bool = False,
    attempted_at: datetime | None = None,
    settings: RadarEnrichmentSettings | None = None,
) -> ChannelSubscriberBatchApplyReport:
    cfg = settings or radar_enrichment_settings
    stamp = attempted_at or datetime.now(timezone.utc)
    report = ChannelSubscriberBatchApplyReport()
    rows_by_id = _load_channels(session, batch_ids)

    for cid in batch_ids:
        row = rows_by_id.get(cid)
        try:
            if network_failed:
                status = SUBSCRIBERS_API_FAILED
                reason = REASON_NETWORK_FAILED
                if row is not None:
                    status = apply_channel_subscriber_details(row, None, checked_at=stamp, failed=True)
                record_channel_subscriber_attempt(
                    session,
                    channel_id=cid,
                    outcome=status,
                    attempted_at=stamp,
                )
                report.failed += 1
                report.outcomes.append(
                    ChannelSubscriberIdOutcome(
                        channel_id=cid,
                        reason=reason,
                        api_status=status,
                        retry_after=subscriber_retry_after(status, checked_at=stamp, settings=cfg),
                    ),
                )
                continue

            details = details_map.get(cid)
            if details is None:
                status = SUBSCRIBERS_API_MISSING
                reason = REASON_API_NO_ITEM
                if row is not None:
                    status = apply_channel_subscriber_details(row, None, checked_at=stamp)
                record_channel_subscriber_attempt(
                    session,
                    channel_id=cid,
                    outcome=status,
                    attempted_at=stamp,
                )
                report.missing += 1
                report.outcomes.append(
                    ChannelSubscriberIdOutcome(
                        channel_id=cid,
                        reason=reason,
                        api_status=status,
                        retry_after=subscriber_retry_after(status, checked_at=stamp, settings=cfg),
                    ),
                )
                continue

            upserted = False
            if row is None:
                upsert_channel_from_youtube_api(session, details, created_at=stamp)
                session.flush()
                row = session.get(Channel, cid)
                upserted = True
            if row is None:
                raise RuntimeError(f"channel row missing after upsert: {cid}")

            status = apply_channel_subscriber_details(row, details, checked_at=stamp)
            record_channel_subscriber_attempt(session, channel_id=cid, outcome=status, attempted_at=stamp)
            reason = REASON_API_ITEM_UPSERTED if upserted else REASON_API_ITEM_EXISTING
            if status == SUBSCRIBERS_API_KNOWN:
                report.known += 1
            elif status == SUBSCRIBERS_API_HIDDEN:
                report.hidden += 1
            elif status == SUBSCRIBERS_API_MISSING:
                report.missing += 1
            else:
                report.failed += 1
            report.outcomes.append(
                ChannelSubscriberIdOutcome(
                    channel_id=cid,
                    reason=reason,
                    api_status=status,
                    retry_after=subscriber_retry_after(status, checked_at=stamp, settings=cfg),
                ),
            )
        except Exception:
            record_channel_subscriber_attempt(
                session,
                channel_id=cid,
                outcome=SUBSCRIBERS_API_FAILED,
                attempted_at=stamp,
            )
            report.failed += 1
            report.outcomes.append(
                ChannelSubscriberIdOutcome(
                    channel_id=cid,
                    reason=REASON_PERSIST_ERROR,
                    api_status=SUBSCRIBERS_API_FAILED,
                    retry_after=subscriber_retry_after(SUBSCRIBERS_API_FAILED, checked_at=stamp, settings=cfg),
                ),
            )
            continue

    session.flush()
    return report


def attempt_subscriber_fetch_due(
    attempt: ChannelSubscriberEnrichmentAttempt,
    *,
    now: datetime,
    settings: RadarEnrichmentSettings | None = None,
) -> bool:
    cfg = settings or radar_enrichment_settings
    status = attempt.last_outcome
    checked = attempt.last_attempt_at
    if status == SUBSCRIBERS_API_KNOWN:
        if cfg.subscriber_known_recheck_days <= 0:
            return False
        return ensure_utc(checked) <= now - timedelta(days=cfg.subscriber_known_recheck_days)
    if status == SUBSCRIBERS_API_HIDDEN:
        return ensure_utc(checked) <= now - timedelta(hours=cfg.subscriber_hidden_cooldown_hours)
    if status in (SUBSCRIBERS_API_FAILED, SUBSCRIBERS_API_MISSING):
        return ensure_utc(checked) <= now - timedelta(hours=cfg.subscriber_retry_after_hours)
    return True
