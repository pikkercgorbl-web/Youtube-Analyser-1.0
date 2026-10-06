"""Channel momentum from observed Radar videos (Stage 1.22A). Observation windows, not quality rules."""

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median

from app.models.orm import ChannelSnapshot, Video
from app.services.attention_delayed_outcome import delayed_outcome_for_video
from app.services.attention_engine_types import (
    REASON_CONFIRMED_72H_CLUSTER,
    REASON_CONTENT_MOMENTUM,
    REASON_MULTI_BREAKOUT,
    REASON_SUBSCRIBER_GROWTH,
    REASON_VPH_ABOVE_PREVIOUS,
    AttentionEngineConfig,
    ChannelMomentum,
)
from app.services.attention_evidence import AttentionEvidenceBundle
from app.services.breakout_ranking_service import breakout_fundamental_eligibility
from app.services.metrics import ensure_utc
from app.services.monitoring_tier_budget_policy import DEFAULT_MAX_AGE_MONITORING_HOURS

MIN_RECENT_VIDEOS = 2
MIN_COMPARABLE_VPH = 2
MIN_SUBSCRIBER_SNAPSHOTS = 2


def _in_window(published: datetime | None, start: datetime, end: datetime) -> bool:
    if published is None:
        return False
    value = ensure_utc(published)
    return start < value <= end


def _vph_for(bundle: AttentionEvidenceBundle, video: Video) -> float | None:
    rec = bundle.records.get(video.id)
    if rec is not None:
        return rec.vph
    state = bundle.extra_video_states.get(video.id)
    return state.raw_vph if state is not None else None


def _breakout_eligible(bundle: AttentionEvidenceBundle, video: Video) -> bool:
    rec = bundle.records.get(video.id)
    if rec is not None:
        return rec.breakout_eligible
    state = bundle.extra_video_states.get(video.id)
    if state is None:
        return False
    ok, _ = breakout_fundamental_eligibility(
        state,
        max_age_monitoring_hours=DEFAULT_MAX_AGE_MONITORING_HOURS,
    )
    return ok


def _subscriber_growth(
    snapshots: list[ChannelSnapshot],
    *,
    lookback_start: datetime,
    now: datetime,
) -> tuple[bool, int | None, float | None, int | None]:
    """
    Require ≥2 ChannelSnapshot rows with subscribers > 0 in [lookback_start, now].
    Missing history → unavailable (not 0).
    """
    usable: list[ChannelSnapshot] = []
    start = ensure_utc(lookback_start)
    end = ensure_utc(now)
    for row in snapshots:
        if row.subscribers_count is None or int(row.subscribers_count) <= 0:
            continue
        recorded = ensure_utc(row.recorded_at)
        if start <= recorded <= end:
            usable.append(row)
    if len(usable) < MIN_SUBSCRIBER_SNAPSHOTS:
        return False, None, None, None
    usable.sort(key=lambda row: ensure_utc(row.recorded_at))
    first = int(usable[0].subscribers_count)
    last = int(usable[-1].subscribers_count)
    if first <= 0:
        return False, None, None, last
    absolute = last - first
    pct = round((absolute / first) * 100.0, 4)
    return True, absolute, pct, last


def build_channel_momentum(
    bundle: AttentionEvidenceBundle,
    config: AttentionEngineConfig,
    *,
    now: datetime,
) -> list[ChannelMomentum]:
    end = ensure_utc(now)
    recent_start = end - timedelta(days=config.channel_recent_days)
    previous_start = recent_start - timedelta(days=config.channel_previous_days)
    lookback_start = previous_start
    rows: list[ChannelMomentum] = []

    title_by_channel: dict[str, str] = {}
    subs_by_channel: dict[str, int | None] = {}
    for rec in bundle.records.values():
        if rec.channel is not None:
            title_by_channel.setdefault(rec.video.channel_id, rec.channel.title)
        subs_by_channel.setdefault(rec.video.channel_id, rec.subscribers)

    for channel_id, videos in bundle.extra_channel_videos.items():
        recent = [v for v in videos if _in_window(v.published_at, recent_start, end)]
        previous = [v for v in videos if _in_window(v.published_at, previous_start, recent_start)]
        if len(recent) < MIN_RECENT_VIDEOS:
            continue
        title = title_by_channel.get(channel_id, channel_id)
        latest_subs = subs_by_channel.get(channel_id)

        recent_vph = [v for v in (_vph_for(bundle, vid) for vid in recent) if v is not None]
        prev_vph = [v for v in (_vph_for(bundle, vid) for vid in previous) if v is not None]
        recent_median = float(median(recent_vph)) if len(recent_vph) >= MIN_COMPARABLE_VPH else None
        previous_median = float(median(prev_vph)) if len(prev_vph) >= MIN_COMPARABLE_VPH else None
        ratio = None
        if recent_median is not None and previous_median is not None and previous_median > 0:
            ratio = round(recent_median / previous_median, 4)

        breakout_n = sum(1 for vid in recent if _breakout_eligible(bundle, vid))
        confirmed_n = 0
        for vid in recent:
            rec = bundle.records.get(vid.id)
            snaps = bundle.extra_snapshots_by_video.get(vid.id, [])
            hits = bundle.extra_hits_by_video.get(vid.id, rec.hits if rec else [])
            state, _ = delayed_outcome_for_video(
                video_id=vid.id,
                hits=hits,
                snapshots=snaps if snaps else (rec.snapshots if rec else []),
                now=end,
            )
            if state == "confirmed":
                confirmed_n += 1

        growth_ok, growth_abs, growth_pct, snap_latest = _subscriber_growth(
            bundle.channel_snapshots.get(channel_id, []),
            lookback_start=lookback_start,
            now=end,
        )
        if snap_latest is not None:
            latest_subs = snap_latest

        seen_times = [ensure_utc(v.published_at) for v in videos if v.published_at is not None]
        ranked_recent = sorted(
            recent,
            key=lambda v: (-(_vph_for(bundle, v) or 0.0), v.id),
        )
        representative = tuple(v.id for v in ranked_recent[:5])

        codes: list[str] = []
        humans: list[str] = []
        if breakout_n >= 2:
            codes.append(REASON_MULTI_BREAKOUT)
            humans.append(f"{breakout_n} breakout-eligible videos in the last {config.channel_recent_days} days")
        if ratio is not None and ratio >= 1.5:
            codes.append(REASON_VPH_ABOVE_PREVIOUS)
            humans.append(
                f"recent median VPH {recent_median:.1f} is {ratio:.2f}× previous-window median {previous_median:.1f}",
            )
        if confirmed_n >= 2:
            codes.append(REASON_CONFIRMED_72H_CLUSTER)
            humans.append(f"{confirmed_n} recent videos with confirmed 72h view growth")
        if growth_ok and growth_abs is not None and growth_abs > 0:
            codes.append(REASON_SUBSCRIBER_GROWTH)
            humans.append(
                f"ChannelSnapshot history shows +{growth_abs} subscribers "
                f"({growth_pct:.1f}%) over the observation windows",
            )
        if codes:
            codes.append(REASON_CONTENT_MOMENTUM)
            humans.append(
                f"{len(recent)} recent videos vs {len(previous)} in the preceding "
                f"{config.channel_previous_days} days (observation windows, not a quality rule)",
            )

        if not codes:
            continue
        if (
            len(previous) < MIN_RECENT_VIDEOS
            and ratio is None
            and not (growth_ok and growth_abs is not None and growth_abs > 0)
        ):
            continue

        rows.append(
            ChannelMomentum(
                channel_id=channel_id,
                channel_title=title,
                subscriber_count_latest=latest_subs,
                observed_video_count=len(videos),
                recent_video_count=len(recent),
                previous_video_count=len(previous),
                breakout_video_count=breakout_n,
                confirmed_72h_count=confirmed_n,
                recent_median_vph=recent_median,
                previous_median_vph=previous_median,
                recent_median_vph_vs_previous=ratio,
                subscriber_growth_absolute=growth_abs if growth_ok else None,
                subscriber_growth_pct=growth_pct if growth_ok else None,
                subscriber_growth_available=growth_ok,
                first_observed_at=min(seen_times) if seen_times else None,
                latest_observed_at=max(seen_times) if seen_times else None,
                representative_video_ids=representative,
                reason_codes=tuple(dict.fromkeys(codes)),
                human_reasons=tuple(humans),
                recent_window_days=config.channel_recent_days,
                previous_window_days=config.channel_previous_days,
            ),
        )

    def sort_key(item: ChannelMomentum) -> tuple:
        ratio = item.recent_median_vph_vs_previous
        ratio_sort = -(ratio) if ratio is not None else 0.0
        return (
            -item.breakout_video_count,
            -item.confirmed_72h_count,
            ratio_sort,
            -item.recent_video_count,
            item.channel_id,
        )

    rows.sort(key=sort_key)
    return rows[: config.channel_limit]
