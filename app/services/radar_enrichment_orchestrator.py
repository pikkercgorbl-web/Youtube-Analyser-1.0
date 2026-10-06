"""Radar enrichment pass: subscribers then format (Stage 2.5)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.orm import Session

from app.integrations.youtube.client import YouTubeVideoDetails
from app.services.channel_subscriber_enrichment import apply_subscriber_enrichment_batch
from app.services.radar_api_budget import (
    BUDGET_KIND_CHANNELS_LIST,
    BUDGET_KIND_VIDEOS_LIST,
    record_http_requests,
    remaining_id_units,
    try_reserve_id_units,
)
from app.services.radar_enrichment_config import (
    CHANNELS_LIST_BATCH_SIZE,
    radar_enrichment_settings,
)
from app.services.radar_enrichment_selection import (
    RadarEnrichmentPassContext,
    channels_with_known_subs_at_most,
    diagnose_format_enrichment_selection,
    select_format_enrichment_video_ids,
    select_subscriber_enrichment_channel_ids,
)
from app.services.unknown_format_enrichment_config import (
    VIDEOS_LIST_BATCH_SIZE,
    unknown_format_enrichment_settings,
)
from app.services.video_format_batch_apply import apply_format_details_for_batch
from app.services.video_format_from_api import chunk_video_ids

logger = logging.getLogger(__name__)


class ChannelsListClient(Protocol):
    def get_channels(self, channel_ids: list[str]) -> dict:
        ...


class VideosListClient(Protocol):
    def get_videos(self, video_ids: list[str]) -> list[object]:
        ...


@dataclass
class RadarEnrichmentPassReport:
    dry_run: bool = False
    subscriber_channels_planned: int = 0
    subscriber_channels_processed: int = 0
    subscriber_http_batches: int = 0
    format_videos_planned: int = 0
    format_videos_processed: int = 0
    format_http_batches: int = 0
    format_confirmed_regular: int = 0
    format_stream: int = 0
    format_short: int = 0
    format_missing: int = 0
    format_failed: int = 0
    channel_budget_reserved: int = 0
    video_budget_reserved: int = 0
    errors: tuple[str, ...] = ()
    notes: dict[str, object] = field(default_factory=dict)


def _run_subscriber_phase(
    session: Session,
    youtube_client: ChannelsListClient,
    *,
    context: RadarEnrichmentPassContext,
    dry_run: bool,
    now: datetime,
) -> tuple[RadarEnrichmentPassReport, RadarEnrichmentPassContext, set[str]]:
    settings = radar_enrichment_settings
    report = RadarEnrichmentPassReport(dry_run=dry_run)
    fetched = set(context.fetched_channel_ids)
    touched_channel_ids: set[str] = set()

    pass_cap = settings.channel_subscriber_enrichment_pass_limit
    daily_cap = settings.channel_subscriber_enrichment_daily_limit
    remaining_daily = remaining_id_units(
        session,
        budget_kind=BUDGET_KIND_CHANNELS_LIST,
        daily_limit=daily_cap,
        now=now,
    )
    plan_count = min(pass_cap, remaining_daily)
    channel_ids = select_subscriber_enrichment_channel_ids(
        session,
        limit=plan_count,
        context=context,
        now=now,
    )
    report.subscriber_channels_planned = len(channel_ids)
    if not channel_ids:
        return report, context, touched_channel_ids

    batch_outcomes: list[dict[str, object]] = []

    for batch in chunk_video_ids(channel_ids, batch_size=CHANNELS_LIST_BATCH_SIZE):
        batch = [cid for cid in batch if cid not in fetched]
        if not batch:
            continue
        if dry_run:
            report.subscriber_http_batches += 1
            report.subscriber_channels_processed += len(batch)
            batch_outcomes.append(
                {
                    "dry_run": True,
                    "channel_ids": list(batch),
                    "planned": len(batch),
                },
            )
            continue

        reservation = try_reserve_id_units(
            session,
            budget_kind=BUDGET_KIND_CHANNELS_LIST,
            unit_count=len(batch),
            daily_limit=daily_cap,
            now=now,
        )
        report.channel_budget_reserved += reservation.reserved
        batch = batch[: reservation.reserved]
        if not batch:
            break
        session.commit()

        details_map = {}
        network_failed = False
        try:
            details_map = youtube_client.get_channels(batch)
        except Exception as exc:
            network_failed = True
            report.errors += (f"channels.list batch failed: {exc}",)
            logger.warning("channels.list batch failed: %s", exc)

        try:
            record_http_requests(
                session,
                budget_kind=BUDGET_KIND_CHANNELS_LIST,
                request_count=1,
                now=now,
            )
            report.subscriber_http_batches += 1
            apply_report = apply_subscriber_enrichment_batch(
                session,
                batch,
                details_map,
                network_failed=network_failed,
                attempted_at=now,
            )
            session.commit()
            report.subscriber_channels_processed += len(batch)
            fetched.update(batch)
            touched_channel_ids.update(batch)
            batch_outcomes.append(
                {
                    "channel_ids": list(batch),
                    "outcomes": [
                        {
                            "channel_id": o.channel_id,
                            "reason": o.reason,
                            "api_status": o.api_status,
                            "retry_after": o.retry_after.isoformat() if o.retry_after else None,
                        }
                        for o in apply_report.outcomes
                    ],
                    "counts": {
                        "known": apply_report.known,
                        "hidden": apply_report.hidden,
                        "missing": apply_report.missing,
                        "failed": apply_report.failed,
                    },
                },
            )
        except Exception as exc:
            session.rollback()
            report.errors += (f"channel persist failed: {exc}",)
            logger.exception("channel enrichment persist failed")

    report.notes["subscriber_batches"] = batch_outcomes
    new_ctx = context if dry_run else replace(context, fetched_channel_ids=frozenset(fetched))
    return report, new_ctx, touched_channel_ids


def _run_format_phase(
    session: Session,
    youtube_client: VideosListClient,
    *,
    context: RadarEnrichmentPassContext,
    dry_run: bool,
    now: datetime,
    prior: RadarEnrichmentPassReport,
    subscriber_touched_channel_ids: set[str],
) -> tuple[RadarEnrichmentPassReport, RadarEnrichmentPassContext]:
    settings = radar_enrichment_settings
    report = prior
    fetched = set(context.fetched_video_ids)

    priority_channels = frozenset(subscriber_touched_channel_ids)
    if subscriber_touched_channel_ids and not dry_run:
        session.expire_all()
        format_eligible_on_touched = channels_with_known_subs_at_most(
            session,
            subscriber_touched_channel_ids,
        )
        report.notes["format_selection_after_subscribers"] = diagnose_format_enrichment_selection(
            session,
            channel_ids=subscriber_touched_channel_ids,
            context=context,
            now=now,
        )
        report.notes["subscriber_touched_eligible_for_format"] = sorted(format_eligible_on_touched)

    pass_cap = settings.video_format_enrichment_pass_limit
    daily_cap = unknown_format_enrichment_settings.unknown_format_enrichment_daily_video_limit
    remaining_daily = remaining_id_units(
        session,
        budget_kind=BUDGET_KIND_VIDEOS_LIST,
        daily_limit=daily_cap,
        now=now,
    )
    plan_count = min(pass_cap, remaining_daily)
    format_profile: dict[str, int] = {}
    video_ids = select_format_enrichment_video_ids(
        session,
        limit=plan_count,
        context=context,
        now=now,
        priority_channel_ids=priority_channels,
        selection_profile=format_profile,
    )
    if format_profile:
        report.notes["format_selection_profile"] = format_profile
    report.format_videos_planned = len(video_ids)
    if not video_ids:
        new_ctx = context if dry_run else replace(context, fetched_video_ids=frozenset(fetched))
        return report, new_ctx

    for batch in chunk_video_ids(video_ids, batch_size=VIDEOS_LIST_BATCH_SIZE):
        batch = [vid for vid in batch if vid not in fetched]
        if not batch:
            continue
        if dry_run:
            report.format_http_batches += 1
            report.format_videos_processed += len(batch)
            continue

        reservation = try_reserve_id_units(
            session,
            budget_kind=BUDGET_KIND_VIDEOS_LIST,
            unit_count=len(batch),
            daily_limit=daily_cap,
            now=now,
        )
        report.video_budget_reserved += reservation.reserved
        batch = batch[: reservation.reserved]
        if not batch:
            break
        session.commit()

        details_by_id: dict[str, YouTubeVideoDetails] = {}
        try:
            raw = youtube_client.get_videos(batch)
            report.format_http_batches += 1
            for item in raw:
                if isinstance(item, YouTubeVideoDetails):
                    details_by_id[item.video_id] = item
        except Exception as exc:
            report.errors += (f"videos.list batch failed: {exc}",)
            logger.warning("videos.list batch failed: %s", exc)
            try:
                record_http_requests(
                    session,
                    budget_kind=BUDGET_KIND_VIDEOS_LIST,
                    request_count=1,
                    now=now,
                )
                apply_format_details_for_batch(session, batch, {}, attempted_at=now)
                session.commit()
            except Exception:
                session.rollback()
            fetched.update(batch)
            continue

        try:
            record_http_requests(
                session,
                budget_kind=BUDGET_KIND_VIDEOS_LIST,
                request_count=1,
                now=now,
            )
            apply_report = apply_format_details_for_batch(
                session,
                batch,
                details_by_id,
                attempted_at=now,
            )
            session.commit()
            report.format_videos_processed += len(batch)
            report.format_confirmed_regular += apply_report.confirmed_regular
            report.format_stream += apply_report.stream
            report.format_short += apply_report.short
            report.format_missing += apply_report.missing
            report.format_failed += apply_report.failed
            fetched.update(batch)
        except Exception as exc:
            session.rollback()
            report.errors += (f"format persist failed: {exc}",)
            logger.exception("format enrichment persist failed")

    new_ctx = context if dry_run else replace(context, fetched_video_ids=frozenset(fetched))
    return report, new_ctx


def run_radar_enrichment_pass(
    session: Session,
    youtube_client: ChannelsListClient | VideosListClient,
    *,
    context: RadarEnrichmentPassContext | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> RadarEnrichmentPassReport:
    """
    Subscribers first, then format for videos on channels with known subs ≤100k.

    Commits before outbound HTTP; enrichment failures should be handled by caller.
    Dry-run does not reserve budget, call HTTP, or mutate pass de-duplication state.
    """
    stamp = now or datetime.now(timezone.utc)
    ctx = context or RadarEnrichmentPassContext()
    sub_report, ctx, touched = _run_subscriber_phase(
        session,
        youtube_client,
        context=ctx,
        dry_run=dry_run,
        now=stamp,
    )
    final_report, _ = _run_format_phase(
        session,
        youtube_client,
        context=ctx,
        dry_run=dry_run,
        now=stamp,
        prior=sub_report,
        subscriber_touched_channel_ids=touched,
    )
    final_report.notes["pass_sequence"] = ctx.pass_sequence
    final_report.notes["discovery_run_id"] = ctx.discovery_run_id
    final_report.notes["dry_run_preserves_fetched_state"] = dry_run
    return final_report
