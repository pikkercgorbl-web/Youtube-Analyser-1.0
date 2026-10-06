#!/usr/bin/env python3
"""Audit data pipeline for Channel Momentum (read-only, local DB)."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

HORIZON = 24
MOMENTUM_TOL = 6.0
MOMENTUM_WINDOW_MAX_AGE = HORIZON + MOMENTUM_TOL  # 30h


@dataclass
class VideoPipelineRow:
    video_id: str
    channel_id: str | None
    published_at: str | None
    age_hours_now: float | None
    first_discovered_at: str | None
    delay_discovery_to_publish_h: float | None
    subscribers_api_status: str | None
    subscribers_checked_at: str | None
    delay_discovery_to_subs_check_h: float | None
    format_outcome: str | None
    format_attempt_at: str | None
    delay_discovery_to_format_h: float | None
    format_confirmed: bool
    monitoring_eligible_now: bool
    monitoring_block_reason: str | None
    snapshot_count: int
    snapshot_in_momentum_window: bool
    best_snapshot_age_h: float | None
    momentum_window_status: str
    skip_reasons: list[str]
    can_still_get_momentum_snapshot: bool


def _hours_between(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return round((ensure_utc(b) - ensure_utc(a)).total_seconds() / 3600.0, 4)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def main() -> int:
    load_dotenv(ROOT / ".env")
    from sqlalchemy import func, select

    from app.models.db import SessionLocal
    from app.models.orm import (
        Channel,
        ChannelSubscriberEnrichmentAttempt,
        KeywordDiscoveryHit,
        Video,
        VideoFormat,
        VideoFormatEnrichmentAttempt,
    )
    from app.services.attention_engine_types import AttentionEngineConfig
    from app.services.channel_momentum_age_vph import select_age_aligned_measurement
    from app.services.metrics import utc_now
    from app.services.monitoring_radar_eligibility import monitoring_video_eligible
    from app.services.monitoring_tier_budget_policy import (
        MonitoringTierPolicy,
        TIER_A_CHECKPOINTS,
        TIER_B_CHECKPOINTS,
        TIER_C_CHECKPOINTS,
    )
    from app.services.radar_api_budget import (
        BUDGET_KIND_VIDEOS_LIST,
        budget_day_status,
        remaining_id_units,
    )
    from app.services.radar_target_eligibility import radar_target_eligible
    from app.services.snapshot_collection_policy import (
        SnapshotCollectionPolicy,
        checkpoint_expires_at_age_hours,
        checkpoint_match_window,
        plan_video_revisits,
    )
    from app.services.unknown_format_enrichment_config import unknown_format_enrichment_settings
    from app.services.video_format_api_verification import load_api_format_confirmed_video_ids
    from app.services.video_snapshot_storage import get_snapshots_for_videos

    session = SessionLocal()
    now = utc_now()
    cfg = AttentionEngineConfig()

    # Fresh cohort for pipeline timing (discovery → enrichment → 30h window)
    cohort_start = now - timedelta(hours=72)
    videos = list(
        session.scalars(
            select(Video).where(
                Video.published_at >= cohort_start,
                Video.published_at <= now,
                Video.content_format.not_in((VideoFormat.SHORT, VideoFormat.LIVE)),
            ),
        ).all(),
    )
    video_ids = [v.id for v in videos]
    channel_ids = list({v.channel_id for v in videos if v.channel_id})
    channels = {
        c.id: c
        for c in session.scalars(select(Channel).where(Channel.id.in_(channel_ids))).all()
    }
    confirmed = load_api_format_confirmed_video_ids(session, video_ids)

    hits_by_video: dict[str, list] = defaultdict(list)
    for hit in session.scalars(
        select(KeywordDiscoveryHit).where(KeywordDiscoveryHit.video_id.in_(video_ids)),
    ).all():
        hits_by_video[hit.video_id].append(hit)

    format_attempts = {
        row.video_id: row
        for row in session.scalars(
            select(VideoFormatEnrichmentAttempt).where(
                VideoFormatEnrichmentAttempt.video_id.in_(video_ids),
            ),
        ).all()
    }
    sub_attempts = {
        row.channel_id: row
        for row in session.scalars(
            select(ChannelSubscriberEnrichmentAttempt).where(
                ChannelSubscriberEnrichmentAttempt.channel_id.in_(channel_ids),
            ),
        ).all()
    }

    snaps_by_video: dict[str, list] = defaultdict(list)
    for chunk_start in range(0, len(video_ids), 400):
        chunk = video_ids[chunk_start : chunk_start + 400]
        for snap in get_snapshots_for_videos(session, chunk):
            snaps_by_video[snap.video_id].append(snap)

    pol = SnapshotCollectionPolicy()
    tier_policy = MonitoringTierPolicy()
    cp24_expires = checkpoint_expires_at_age_hours(24, pol)
    cp24_match = checkpoint_match_window(24, pol)

    pipeline_rows: list[VideoPipelineRow] = []
    delay_format: list[float] = []
    delay_subs: list[float] = []
    enrichment_before_18h = 0
    enrichment_before_24h = 0
    enrichment_total_with_discovery = 0

    for v in videos:
        published = ensure_utc(v.published_at) if v.published_at else None
        age_now = (now - published).total_seconds() / 3600.0 if published else None
        hits = hits_by_video.get(v.id, [])
        first_hit = min(hits, key=lambda h: ensure_utc(h.discovered_at)) if hits else None
        discovered_at = ensure_utc(first_hit.discovered_at) if first_hit else None

        ch = channels.get(v.channel_id) if v.channel_id else None
        fmt_row = format_attempts.get(v.id)
        sub_row = sub_attempts.get(v.channel_id) if v.channel_id else None

        fmt_at = ensure_utc(fmt_row.last_attempt_at) if fmt_row and fmt_row.last_attempt_at else None
        sub_at = None
        if ch and ch.subscribers_api_checked_at:
            sub_at = ensure_utc(ch.subscribers_api_checked_at)
        elif sub_row and sub_row.last_attempt_at:
            sub_at = ensure_utc(sub_row.last_attempt_at)

        fmt_confirmed = v.id in confirmed
        d_fmt = _hours_between(discovered_at, fmt_at) if discovered_at else None
        d_sub = _hours_between(discovered_at, sub_at) if discovered_at else None
        if d_fmt is not None:
            delay_format.append(d_fmt)
        if d_sub is not None:
            delay_subs.append(d_sub)
        if discovered_at and fmt_at:
            enrichment_total_with_discovery += 1
            if fmt_at <= discovered_at + timedelta(hours=18):
                enrichment_before_18h += 1
            if fmt_at <= discovered_at + timedelta(hours=24):
                enrichment_before_24h += 1

        snaps = snaps_by_video.get(v.id, [])
        meas = None
        if published:
            meas = select_age_aligned_measurement(
                video_id=v.id,
                published_at=published,
                snapshots=snaps,
                horizon_hours=HORIZON,
                tolerance_hours=MOMENTUM_TOL,
            )
        in_window = meas is not None
        best_age = meas.actual_age_hours if meas else None

        if age_now is None:
            win_status = "no_publish"
        elif age_now <= MOMENTUM_WINDOW_MAX_AGE:
            win_status = "window_open" if not in_window else "window_satisfied"
        elif in_window:
            win_status = "satisfied_late"
        else:
            win_status = "window_missed"

        latest_snap = max(snaps, key=lambda s: ensure_utc(s.captured_at)) if snaps else None
        mon_ok = monitoring_video_eligible(
            video=v,
            channel=ch,
            latest_snapshot=latest_snap,
            confirmed_regular_ids=confirmed,
        )
        mon_block = None
        if not radar_target_eligible(video=v, channel=ch, latest_snapshot=latest_snap):
            mon_block = "radar_target"
        elif v.content_format in (VideoFormat.SHORT, VideoFormat.LIVE, VideoFormat.UNKNOWN):
            mon_block = "format_class"
        elif not fmt_confirmed:
            mon_block = "format_not_confirmed"

        skips: list[str] = []
        if not hits:
            skips.append("no_discovery_hit")
        if ch and ch.subscribers_api_status not in (None, "known"):
            skips.append(f"subs_{ch.subscribers_api_status}")
        if not fmt_confirmed:
            skips.append("format_not_confirmed")
        if win_status == "window_missed":
            skips.append("momentum_24h_window_missed")

        can_still = (
            age_now is not None
            and age_now < MOMENTUM_WINDOW_MAX_AGE
            and fmt_confirmed
            and mon_block is None
            and not in_window
        )

        pipeline_rows.append(
            VideoPipelineRow(
                video_id=v.id,
                channel_id=v.channel_id,
                published_at=published.isoformat() if published else None,
                age_hours_now=round(age_now, 2) if age_now is not None else None,
                first_discovered_at=discovered_at.isoformat() if discovered_at else None,
                delay_discovery_to_publish_h=_hours_between(published, discovered_at),
                subscribers_api_status=ch.subscribers_api_status if ch else None,
                subscribers_checked_at=sub_at.isoformat() if sub_at else None,
                delay_discovery_to_subs_check_h=d_sub,
                format_outcome=fmt_row.last_outcome if fmt_row else None,
                format_attempt_at=fmt_at.isoformat() if fmt_at else None,
                delay_discovery_to_format_h=d_fmt,
                format_confirmed=fmt_confirmed,
                monitoring_eligible_now=mon_ok,
                monitoring_block_reason=mon_block,
                snapshot_count=len(snaps),
                snapshot_in_momentum_window=in_window,
                best_snapshot_age_h=best_age,
                momentum_window_status=win_status,
                skip_reasons=skips,
                can_still_get_momentum_snapshot=can_still,
            ),
        )

    # Sample revisit plan at 25h age (scheduler still overdue, momentum still ok)
    sample_plan_25h = plan_video_revisits(
        video_id="synthetic",
        published_at=now - timedelta(hours=25),
        existing_snapshots=[],
        current_time=now,
        policy=SnapshotCollectionPolicy(checkpoint_hours=(6, 12, 24, 48, 72)),
    )
    cp24_plan = next(cp for cp in sample_plan_25h.checkpoints if cp.target_age_hours == 24)

    offline_path = ROOT / "artifacts" / "channel_momentum_offline.json"
    momentum_engine = {}
    if offline_path.is_file():
        momentum_engine = json.loads(offline_path.read_text(encoding="utf-8"))
    measurable_channels = momentum_engine.get("momentum_engine_now", {}).get(
        "channels_with_2plus_measured_recent_and_previous",
    )
    if measurable_channels is None:
        measurable_channels = "run scripts/run_channel_momentum_offline.py"

    daily_limit = unknown_format_enrichment_settings.unknown_format_enrichment_daily_video_limit
    budget_reserved = int(budget_day_status(session, budget_kind=BUDGET_KIND_VIDEOS_LIST, now=now).id_units_reserved)
    budget_remaining = remaining_id_units(
        session,
        budget_kind=BUDGET_KIND_VIDEOS_LIST,
        daily_limit=daily_limit,
        now=now,
    )

    status_counts = Counter(r.momentum_window_status for r in pipeline_rows)
    skip_counts = Counter(reason for r in pipeline_rows for reason in r.skip_reasons)

    report = {
        "computed_at": now.isoformat(),
        "cohort": {"published_since_hours": 72, "video_count": len(pipeline_rows)},
        "pipeline_delays_hours": {
            "discovery_to_format_confirm": {
                "n": len(delay_format),
                "p50": sorted(delay_format)[len(delay_format) // 2] if delay_format else None,
                "p90": sorted(delay_format)[int(len(delay_format) * 0.9)] if len(delay_format) >= 10 else None,
                "max": max(delay_format) if delay_format else None,
            },
            "discovery_to_subscriber_check": {
                "n": len(delay_subs),
                "p50": sorted(delay_subs)[len(delay_subs) // 2] if delay_subs else None,
                "max": max(delay_subs) if delay_subs else None,
            },
            "format_confirmed_before_18h_from_discovery": enrichment_before_18h,
            "format_confirmed_before_24h_from_discovery": enrichment_before_24h,
            "with_discovery_and_format_attempt": enrichment_total_with_discovery,
        },
        "momentum_snapshot_window": {
            "horizon_h": HORIZON,
            "tolerance_h": MOMENTUM_TOL,
            "usable_age_hours_inclusive": [HORIZON - MOMENTUM_TOL, HORIZON + MOMENTUM_TOL],
        },
        "monitoring_checkpoints": {
            "tier_a": list(TIER_A_CHECKPOINTS),
            "tier_b": list(TIER_B_CHECKPOINTS),
            "tier_c": list(TIER_C_CHECKPOINTS),
            "all_tiers_include_24h": 24 in TIER_A_CHECKPOINTS
            and 24 in TIER_B_CHECKPOINTS
            and 24 in TIER_C_CHECKPOINTS,
            "checkpoint_24h_match_window_age_h": list(cp24_match),
            "checkpoint_24h_expires_at_age_h": cp24_expires,
            "momentum_vs_monitoring": (
                "Monitoring match window for 24h is ±3.6h (20.4–27.6h); Momentum accepts ±6h (18–30h). "
                f"Scheduler may capture until {cp24_expires}h (overdue), but snapshots after 30h are unusable for Momentum."
            ),
            "synthetic_age_25h_no_snapshots": {
                "cp24_status": cp24_plan.status,
                "cp24_recommended_action": cp24_plan.recommended_action,
                "cp24_expires_at_age_h": cp24_plan.expires_at_age_hours,
            },
        },
        "momentum_measurement_rule": (
            "Uses available eligible subset: requires ≥2 measured recent and ≥2 measured previous; "
            "missing snapshots increment incompleteness notes and do not veto if minimums met."
        ),
        "cohort_coverage": {
            "window_open_can_still_get_snapshot": sum(1 for r in pipeline_rows if r.can_still_get_momentum_snapshot),
            "window_missed_no_momentum_snapshot": status_counts.get("window_missed", 0),
            "already_has_momentum_snapshot": sum(1 for r in pipeline_rows if r.snapshot_in_momentum_window),
            "monitoring_eligible_now": sum(1 for r in pipeline_rows if r.monitoring_eligible_now),
            "format_confirmed": sum(1 for r in pipeline_rows if r.format_confirmed),
        },
        "momentum_engine_now": {
            "source": str(offline_path) if offline_path.is_file() else "missing",
            "published_signals": momentum_engine.get("published_signal_count"),
            "channels_with_2plus_measured_recent_and_previous": measurable_channels,
            "rejection_top": momentum_engine.get("rejection_primary_diagnostic_counts"),
        },
        "enrichment_budget_today": {
            "videos_list_daily_limit": daily_limit,
            "reserved": budget_reserved,
            "remaining": budget_remaining,
        },
        "skip_reason_counts": dict(skip_counts.most_common(15)),
        "sample_pipeline_rows": [asdict(r) for r in pipeline_rows[:25]],
    }

    out = ROOT / "artifacts" / "momentum_data_pipeline_audit.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "sample_pipeline_rows"}, indent=2))
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
