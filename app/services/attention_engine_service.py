"""Attention Engine orchestration (Stage 1.22A). Compute from existing Radar evidence only."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.services.attention_channel_momentum import build_channel_momentum
from app.services.attention_engine_types import (
    ATTENTION_TIMEZONE,
    AttentionEngineConfig,
    AttentionEngineResult,
    AttentionSummary,
)
from app.services.attention_evidence import load_attention_evidence
from app.services.radar_target_eligibility import summarize_video_eligibility
from app.services.attention_pattern_families import build_pattern_families, load_family_identity
from app.services.attention_patterns import build_pattern_candidates
from app.services.attention_video_winners import build_video_winners
from app.services.metrics import ensure_utc, utc_now
from app.services.video_format_api_verification import load_api_format_confirmed_video_ids


def attention_window(
    *,
    now: datetime | None = None,
    window_hours: int = 24,
) -> tuple[datetime, datetime]:
    """UTC exclusive-open window (window_start, window_end] with timezone_name=UTC."""
    end = ensure_utc(now or utc_now())
    start = end - timedelta(hours=window_hours)
    return start, end


def build_attention_summary(
    *,
    config: AttentionEngineConfig,
    computed_at: datetime,
    window_start: datetime,
    window_end: datetime,
    candidate_video_count: int,
    winner_count: int,
    pattern_count: int,
    channel_momentum_count: int,
    source: str,
    run_id: str | None = None,
    notes: dict | None = None,
) -> AttentionSummary:
    return AttentionSummary(
        run_id=run_id,
        computed_at=ensure_utc(computed_at),
        timezone_name=config.timezone_name or ATTENTION_TIMEZONE,
        window_hours=config.window_hours,
        window_start=ensure_utc(window_start),
        window_end=ensure_utc(window_end),
        source=source,
        candidate_video_count=candidate_video_count,
        winner_count=winner_count,
        pattern_count=pattern_count,
        channel_momentum_count=channel_momentum_count,
        video_limit=config.video_limit,
        pattern_limit=config.pattern_limit,
        channel_limit=config.channel_limit,
        notes=notes or {},
    )


def compute_attention_engine(
    session: Session,
    *,
    config: AttentionEngineConfig | None = None,
    now: datetime | None = None,
    source: str = "live_compute",
    run_id: str | None = None,
    require_confirmed_regular_for_publish: bool = False,
) -> AttentionEngineResult:
    """
    One-shot compute. Does not write lifecycle, monitoring, or discovery tables.
    Does not call YouTube HTTP.
    """
    cfg = config or AttentionEngineConfig()
    computed_at = ensure_utc(now or utc_now())
    window_start, window_end = attention_window(now=computed_at, window_hours=cfg.window_hours)
    lookback_days = cfg.channel_recent_days + cfg.channel_previous_days
    lookback_start = window_end - timedelta(days=lookback_days)
    bundle = load_attention_evidence(
        session,
        window_start=window_start,
        window_end=window_end,
        channel_lookback_start=lookback_start,
    )
    eligibility_items = [
        (rec.video, rec.channel, rec.latest_snapshot) for rec in bundle.records.values()
    ]
    eligibility_stats = summarize_video_eligibility(eligibility_items)

    publishable_confirmed: frozenset[str] | None = None
    publishable_pool_count: int | None = None
    if require_confirmed_regular_for_publish:
        all_video_ids = list(bundle.records.keys())
        for channel_videos in bundle.extra_channel_videos.values():
            all_video_ids.extend(v.id for v in channel_videos)
        all_video_ids = list(dict.fromkeys(all_video_ids))
        publishable_confirmed = load_api_format_confirmed_video_ids(session, all_video_ids)
        uncapped_cfg = AttentionEngineConfig(
            window_hours=cfg.window_hours,
            video_limit=10**9,
            pattern_limit=cfg.pattern_limit,
            channel_limit=cfg.channel_limit,
            timezone_name=cfg.timezone_name,
            channel_recent_days=cfg.channel_recent_days,
            channel_previous_days=cfg.channel_previous_days,
            min_acceleration_snapshots=cfg.min_acceleration_snapshots,
            min_pattern_videos=cfg.min_pattern_videos,
            min_pattern_channels=cfg.min_pattern_channels,
            max_keyword_pattern_videos=cfg.max_keyword_pattern_videos,
            breakout_high_rank_max=cfg.breakout_high_rank_max,
            channel_baseline_max_channel_videos=cfg.channel_baseline_max_channel_videos,
        )
        publishable_pool_count = len(
            build_video_winners(
                bundle,
                uncapped_cfg,
                now=computed_at,
                publishable_confirmed_ids=publishable_confirmed,
            ),
        )

    winners = build_video_winners(
        bundle,
        cfg,
        now=computed_at,
        publishable_confirmed_ids=publishable_confirmed,
    )
    patterns = build_pattern_candidates(
        bundle,
        cfg,
        winners=winners,
        now=computed_at,
        publishable_confirmed_ids=publishable_confirmed,
    )
    first_seen: dict[str, datetime] = {}
    titles: dict[str, str] = {}
    for video_id, rec in bundle.records.items():
        titles[video_id] = rec.video.title
        times = []
        if rec.video.published_at is not None:
            times.append(ensure_utc(rec.video.published_at))
        for hit in rec.hits:
            times.append(ensure_utc(hit.discovered_at))
        if times:
            first_seen[video_id] = min(times)
    families, _identity = build_pattern_families(
        patterns,
        now=computed_at,
        identity=load_family_identity(session),
        first_seen=first_seen,
        titles=titles,
    )
    channels = build_channel_momentum(
        bundle,
        cfg,
        now=computed_at,
        publishable_confirmed_ids=publishable_confirmed,
    )
    extra_notes: dict = {}
    if require_confirmed_regular_for_publish:
        extra_notes["published_winners_gating"] = {
            "require_confirmed_regular_before_rank_cap": True,
            "publishable_pool_before_cap": publishable_pool_count,
            "published_after_cap": len(winners),
            "video_limit": cfg.video_limit,
        }
    summary = build_attention_summary(
        config=cfg,
        computed_at=computed_at,
        window_start=window_start,
        window_end=window_end,
        candidate_video_count=len(bundle.records),
        winner_count=len(winners),
        pattern_count=len(patterns),
        channel_momentum_count=len(channels),
        source=source,
        run_id=run_id,
        notes={
            **extra_notes,
            "sort_video_winners": "breakout_rank asc, accelerating first, vph desc, video_id",
            "sort_patterns": "channel_count desc, breakout_video_count desc, videos_last_24h desc, video_count desc, pattern_key",
            "sort_pattern_families": "channel_count desc, support_sources count desc, breakout_eligible_count desc, last_24h desc, video_count desc, family_key",
            "pattern_family_count": len(families),
            "pattern_family_identity": "reuse stored family_key when membership grows; mint family:{kind}:{core-hash} when unseen",
            "sort_channels": "recent_improvement_count desc, age_aligned_vph_ratio desc, recent_measurable_count desc, channel_id",
            "channel_windows": {
                "recent_days": cfg.channel_recent_days,
                "previous_days": cfg.channel_previous_days,
                "kind": "observation_windows",
            },
            "channel_momentum_measurement": {
                "horizon_hours": cfg.channel_momentum_horizon_hours,
                "horizon_tolerance_hours": cfg.channel_momentum_horizon_tolerance_hours,
                "improvement_ratio": cfg.channel_momentum_improvement_ratio,
                "kind": "age_aligned_snapshot_vph_from_published_at",
            },
            "acceleration_min_snapshots": cfg.min_acceleration_snapshots,
            "pattern_min_videos": cfg.min_pattern_videos,
            "pattern_min_channels": cfg.min_pattern_channels,
            "timezone": ATTENTION_TIMEZONE,
            "radar_target_eligibility": eligibility_stats.to_dict(),
            "radar_target_eligibility_unique": eligibility_stats.unique_rejection_summary(),
            "radar_target_eligibility_counting": (
                "per window AttentionVideoRecord (one row per video_id in bundle.records); "
                "rejections.stream counts videos with content_format=LIVE in DB"
            ),
        },
    )
    return AttentionEngineResult(
        summary=summary,
        video_winners=tuple(winners),
        patterns=tuple(patterns),
        families=tuple(families),
        channels=tuple(channels),
    )
