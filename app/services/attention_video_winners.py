"""VideoWinner builder (Stage 1.22A). Reuses Breakout v1 ordering; no composite score."""

from __future__ import annotations

from datetime import datetime

from app.services.attention_acceleration import classify_acceleration
from app.services.attention_delayed_outcome import delayed_outcome_for_video
from app.services.attention_engine_types import (
    REASON_ACCELERATING,
    REASON_BREAKOUT_ELIGIBLE,
    REASON_BREAKOUT_HIGH_RANK,
    REASON_CHANNEL_RELATIVE_OUTLIER,
    REASON_CONFIRMED_72H,
    REASON_HIGH_CURRENT_VPH,
    REASON_SMALL_CHANNEL_CONTEXT,
    AttentionEngineConfig,
    ChannelRelativeSignal,
    VideoWinner,
    youtube_watch_url,
)
from app.services.attention_evidence import AttentionEvidenceBundle, AttentionVideoRecord
from app.services.channel_velocity_baseline import (
    compute_channel_velocity_baseline_from_snapshots,
    snapshot_record_from_orm,
)
from app.services.radar_candidate_analysis import _percentile


def _human_reasons(codes: list[str], rec: AttentionVideoRecord, *, growth: int | None) -> list[str]:
    lines: list[str] = []
    if REASON_BREAKOUT_HIGH_RANK in codes and rec.breakout_rank is not None:
        lines.append(f"breakout_v1 rank {rec.breakout_rank} in this attention window")
    elif REASON_BREAKOUT_ELIGIBLE in codes:
        lines.append("breakout_v1 eligible (age, format, VPH present)")
    if REASON_HIGH_CURRENT_VPH in codes and rec.vph is not None:
        lines.append(f"current VPH {rec.vph:.1f} is in the top quartile of window-eligible videos")
    if REASON_SMALL_CHANNEL_CONTEXT in codes:
        lines.append(
            "breakout video from a relatively small channel in this window's observed universe "
            "(descriptive context, not a claim that the channel is exploding)",
        )
    if REASON_CHANNEL_RELATIVE_OUTLIER in codes:
        lines.append("VPH is at least 2× this channel's age-aligned historical median (production-ready baseline)")
    if REASON_ACCELERATING in codes:
        lines.append("VPH increased across 3+ snapshots (last ≥ 2× first)")
    if REASON_CONFIRMED_72H in codes:
        if growth is not None:
            lines.append(f"72h horizon snapshot shows +{growth} views vs discovery")
        else:
            lines.append("72h horizon snapshot confirms view growth")
    return lines


def _channel_relative(
    rec: AttentionVideoRecord,
    bundle: AttentionEvidenceBundle,
) -> ChannelRelativeSignal | None:
    if rec.vph is None or rec.state.age_hours is None:
        return ChannelRelativeSignal(
            status="unavailable",
            baseline_quality="none",
            comparable_video_count=0,
            vph_vs_channel_median=None,
            notes=("candidate VPH or age missing",),
        )
    channel_id = rec.video.channel_id
    sibling_ids = [v.id for v in bundle.extra_channel_videos.get(channel_id, [])]
    records = []
    for vid in sibling_ids:
        for row in bundle.extra_snapshots_by_video.get(vid, []):
            records.append(snapshot_record_from_orm(row))
    if not records:
        return ChannelRelativeSignal(
            status="unavailable",
            baseline_quality="none",
            comparable_video_count=0,
            vph_vs_channel_median=None,
            notes=(
                "v1 uses lookback-window VideoSnapshots only; no age-aligned channel history in this window",
            ),
        )
    result = compute_channel_velocity_baseline_from_snapshots(
        channel_id=channel_id,
        candidate_video_id=rec.video.id,
        candidate_age_hours=rec.state.age_hours,
        candidate_vph=rec.vph,
        candidate_published_at=rec.video.published_at,
        candidate_captured_at=rec.latest_snapshot.captured_at if rec.latest_snapshot else None,
        channel_snapshots=records,
    )
    if result.baseline_quality == "production_ready":
        status = "production_ready"
    elif result.baseline_quality == "diagnostic":
        status = "diagnostic"
    else:
        status = "unavailable"
    notes = result.notes + (
        "channel-relative v1 is limited to snapshots already loaded for the attention lookback window",
    )
    return ChannelRelativeSignal(
        status=status,
        baseline_quality=result.baseline_quality,
        comparable_video_count=result.comparable_video_count,
        vph_vs_channel_median=result.vph_vs_channel_median,
        notes=notes,
    )


def build_video_winners(
    bundle: AttentionEvidenceBundle,
    config: AttentionEngineConfig,
    *,
    now: datetime,
) -> list[VideoWinner]:
    records = list(bundle.records.values())
    eligible_vphs = sorted(rec.vph for rec in records if rec.breakout_eligible and rec.vph is not None)
    vph_p75 = _percentile(eligible_vphs, 75) if len(eligible_vphs) >= 4 else None
    known_subs = sorted(rec.subscribers for rec in records if rec.subscribers is not None)
    sub_p25 = _percentile(known_subs, 25) if len(known_subs) >= 4 else None

    winners: list[VideoWinner] = []
    for rec in records:
        acceleration = classify_acceleration(
            [snap.vph for snap in rec.snapshots],
            min_points=config.min_acceleration_snapshots,
        )
        delayed_state, delayed_growth = delayed_outcome_for_video(
            video_id=rec.video.id,
            hits=rec.hits,
            snapshots=rec.snapshots,
            now=now,
        )
        relative: ChannelRelativeSignal | None = None
        if rec.breakout_eligible:
            relative = _channel_relative(rec, bundle)

        codes: list[str] = []
        if rec.breakout_eligible:
            codes.append(REASON_BREAKOUT_ELIGIBLE)
            if rec.breakout_rank is not None and rec.breakout_rank <= config.breakout_high_rank_max:
                codes.append(REASON_BREAKOUT_HIGH_RANK)
        if vph_p75 is not None and rec.vph is not None and rec.vph >= vph_p75 and rec.breakout_eligible:
            codes.append(REASON_HIGH_CURRENT_VPH)
        if (
            rec.breakout_eligible
            and rec.subscribers is not None
            and sub_p25 is not None
            and rec.subscribers <= sub_p25
        ):
            codes.append(REASON_SMALL_CHANNEL_CONTEXT)
        if (
            relative is not None
            and relative.status == "production_ready"
            and relative.vph_vs_channel_median is not None
            and relative.vph_vs_channel_median >= 2.0
        ):
            codes.append(REASON_CHANNEL_RELATIVE_OUTLIER)
        if acceleration == "accelerating":
            codes.append(REASON_ACCELERATING)
        if delayed_state == "confirmed":
            codes.append(REASON_CONFIRMED_72H)

        if not codes:
            continue

        unique_codes = tuple(dict.fromkeys(codes))
        winners.append(
            VideoWinner(
                video_id=rec.video.id,
                title=rec.video.title,
                channel_id=rec.video.channel_id,
                channel_title=rec.channel.title if rec.channel is not None else rec.video.channel_id,
                youtube_url=youtube_watch_url(rec.video.id),
                published_at=rec.video.published_at,
                age_hours=rec.state.age_hours,
                views=rec.views,
                vph=rec.vph,
                subscribers=rec.subscribers,
                breakout_rank=rec.breakout_rank,
                breakout_eligible=rec.breakout_eligible,
                channel_relative_signal=relative,
                acceleration_state=acceleration,
                delayed_outcome_state=delayed_state,
                delayed_outcome_growth=delayed_growth,
                reason_codes=unique_codes,
                human_reasons=tuple(_human_reasons(list(unique_codes), rec, growth=delayed_growth)),
                keyword_ids=tuple(sorted({h.keyword_id for h in rec.hits})),
            ),
        )

    def sort_key(item: VideoWinner) -> tuple:
        rank = item.breakout_rank if item.breakout_rank is not None else 10**9
        accel = 0 if item.acceleration_state == "accelerating" else 1
        vph = -(item.vph or 0.0)
        return (rank, accel, vph, item.video_id)

    winners.sort(key=sort_key)
    return winners[: config.video_limit]
