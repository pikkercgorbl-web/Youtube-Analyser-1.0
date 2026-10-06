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
from app.services.attention_pattern_families import build_pattern_families, load_family_identity
from app.services.attention_patterns import build_pattern_candidates
from app.services.attention_video_winners import build_video_winners
from app.services.metrics import ensure_utc, utc_now


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
    winners = build_video_winners(bundle, cfg, now=computed_at)
    patterns = build_pattern_candidates(bundle, cfg, winners=winners, now=computed_at)
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
    channels = build_channel_momentum(bundle, cfg, now=computed_at)
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
            "sort_video_winners": "breakout_rank asc, accelerating first, vph desc, video_id",
            "sort_patterns": "channel_count desc, breakout_video_count desc, videos_last_24h desc, video_count desc, pattern_key",
            "sort_pattern_families": "channel_count desc, support_sources count desc, breakout_eligible_count desc, last_24h desc, video_count desc, family_key",
            "pattern_family_count": len(families),
            "pattern_family_identity": "reuse stored family_key when membership grows; mint family:{kind}:{core-hash} when unseen",
            "sort_channels": "breakout_video_count desc, confirmed_72h_count desc, recent_median_vph_vs_previous desc, recent_video_count desc, channel_id",
            "channel_windows": {
                "recent_days": cfg.channel_recent_days,
                "previous_days": cfg.channel_previous_days,
                "kind": "observation_windows",
            },
            "acceleration_min_snapshots": cfg.min_acceleration_snapshots,
            "pattern_min_videos": cfg.min_pattern_videos,
            "pattern_min_channels": cfg.min_pattern_channels,
            "timezone": ATTENTION_TIMEZONE,
        },
    )
    return AttentionEngineResult(
        summary=summary,
        video_winners=tuple(winners),
        patterns=tuple(patterns),
        families=tuple(families),
        channels=tuple(channels),
    )
