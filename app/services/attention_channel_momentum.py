"""Channel momentum: repeated age-aligned improvement vs the channel's own prior uploads."""



from __future__ import annotations



from dataclasses import dataclass

from datetime import datetime, timedelta

from statistics import median



from app.models.orm import ChannelSnapshot, Video, VideoFormat, VideoSnapshot

from app.services.attention_delayed_outcome import delayed_outcome_for_video

from app.services.attention_engine_types import (

    REASON_CONTENT_MOMENTUM,

    REASON_CONTEXT_BREAKOUT_ELIGIBLE,

    REASON_CONTEXT_KEYWORD_72H_GROWTH,

    REASON_CONTEXT_SUBSCRIBER_GROWTH,

    REASON_REPEATED_AGE_ALIGNED_IMPROVEMENT,

    AttentionEngineConfig,

    ChannelMomentum,

)

from app.services.attention_evidence import AttentionEvidenceBundle

from app.services.breakout_ranking_service import breakout_fundamental_eligibility

from app.services.channel_momentum_age_vph import AgeAlignedVphMeasurement, select_age_aligned_measurement

from app.services.channel_momentum_diagnostics import (

    DIAG_FORMAT_NOT_CONFIRMED,

    DIAG_INSUFFICIENT_MEASURABLE_PREVIOUS,

    DIAG_INSUFFICIENT_MEASURABLE_RECENT,

    DIAG_INSUFFICIENT_PREVIOUS_IN_WINDOW,

    DIAG_INSUFFICIENT_RECENT_ELIGIBLE,

    DIAG_INSUFFICIENT_REPEATED_IMPROVEMENT,

    DIAG_NO_SNAPSHOT_AT_HORIZON,

    DIAG_SUBSCRIBER_UNAVAILABLE,

    DIAG_ZERO_PREVIOUS_BASELINE,

)

from app.services.metrics import ensure_utc

from app.services.monitoring_tier_budget_policy import DEFAULT_MAX_AGE_MONITORING_HOURS

from app.services.radar_target_eligibility import (

    RADAR_MAX_CHANNEL_SUBSCRIBERS,

    radar_target_eligible,

    resolve_known_subscribers,

)

from app.services.video_format_api_verification import video_id_publishable_with_confirmed_set



MIN_RECENT_VIDEOS = 2

MIN_PREVIOUS_VIDEOS = 2

MIN_IMPROVING_RECENT = 2

MIN_SUBSCRIBER_SNAPSHOTS = 2





def _in_window(published: datetime | None, start: datetime, end: datetime) -> bool:

    if published is None:

        return False

    value = ensure_utc(published)

    return start < value <= end





def _video_snapshots(bundle: AttentionEvidenceBundle, video_id: str) -> list[VideoSnapshot]:

    rec = bundle.records.get(video_id)

    extra = bundle.extra_snapshots_by_video.get(video_id, [])

    if rec is not None:

        merged = list(rec.snapshots)

        seen = {ensure_utc(s.captured_at) for s in merged}

        for snap in extra:

            cap = ensure_utc(snap.captured_at)

            if cap not in seen:

                merged.append(snap)

        return sorted(merged, key=lambda s: (ensure_utc(s.captured_at), s.id))

    return sorted(extra, key=lambda s: (ensure_utc(s.captured_at), s.id))





def _eligible_channel_video(

    bundle: AttentionEvidenceBundle,

    video: Video,

    *,

    publishable_confirmed_ids: frozenset[str] | None = None,

) -> bool:

    rec = bundle.records.get(video.id)

    if rec is not None:

        if not radar_target_eligible(

            video=rec.video,

            channel=rec.channel,

            latest_snapshot=rec.latest_snapshot,

        ):

            return False

        v = rec.video

    else:

        channel = bundle.channels_by_id.get(video.channel_id)

        snap = bundle.extra_latest_snapshots.get(video.id)

        v = video

        if not radar_target_eligible(video=v, channel=channel, latest_snapshot=snap):

            return False

    if publishable_confirmed_ids is None:

        return True

    if v.content_format not in (VideoFormat.MEDIUM, VideoFormat.LONG):

        return False

    return video_id_publishable_with_confirmed_set(

        content_format=v.content_format,

        video_id=v.id,

        confirmed_ids=publishable_confirmed_ids,

    )





def _format_gate_failure(

    bundle: AttentionEvidenceBundle,

    video: Video,

    *,

    publishable_confirmed_ids: frozenset[str] | None,

) -> str | None:

    if publishable_confirmed_ids is None:

        return None

    rec = bundle.records.get(video.id)

    v = rec.video if rec is not None else video

    if v.content_format not in (VideoFormat.MEDIUM, VideoFormat.LONG):

        return "not_regular_format"

    if not video_id_publishable_with_confirmed_set(

        content_format=v.content_format,

        video_id=v.id,

        confirmed_ids=publishable_confirmed_ids,

    ):

        return DIAG_FORMAT_NOT_CONFIRMED

    return None





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





def _measure_video(

    bundle: AttentionEvidenceBundle,

    video: Video,

    *,

    horizon_hours: float,

    tolerance_hours: float,

) -> AgeAlignedVphMeasurement | None:

    if video.published_at is None:

        return None

    from app.services.video_published_at import published_at_usable_for_momentum

    if not published_at_usable_for_momentum(video):

        return None

    snaps = _video_snapshots(bundle, video.id)

    return select_age_aligned_measurement(

        video_id=video.id,

        published_at=video.published_at,

        snapshots=snaps,

        horizon_hours=horizon_hours,

        tolerance_hours=tolerance_hours,

    )





@dataclass(frozen=True, slots=True)

class ChannelMomentumEvaluation:

    momentum: ChannelMomentum | None

    primary_diagnostic: str | None





def evaluate_channel_momentum(

    bundle: AttentionEvidenceBundle,

    config: AttentionEngineConfig,

    *,

    channel_id: str,

    videos: list[Video],

    now: datetime,

    publishable_confirmed_ids: frozenset[str] | None = None,

) -> ChannelMomentumEvaluation:

    end = ensure_utc(now)

    recent_start = end - timedelta(days=config.channel_recent_days)

    previous_start = recent_start - timedelta(days=config.channel_previous_days)

    lookback_start = previous_start

    horizon = float(config.channel_momentum_horizon_hours)

    tolerance = float(config.channel_momentum_horizon_tolerance_hours)

    ratio_threshold = float(config.channel_momentum_improvement_ratio)



    channel_entity = bundle.channels_by_id.get(channel_id)

    title_by_channel: dict[str, str] = {}

    subs_by_channel: dict[str, int | None] = {}

    for rec in bundle.records.values():

        if rec.channel is not None:

            title_by_channel.setdefault(rec.video.channel_id, rec.channel.title)

        subs_by_channel.setdefault(rec.video.channel_id, rec.subscribers)

    latest_subs = subs_by_channel.get(channel_id)

    if latest_subs is None and channel_entity is not None:

        latest_subs = resolve_known_subscribers(channel=channel_entity, latest_snapshot=None)

    if latest_subs is None or latest_subs > RADAR_MAX_CHANNEL_SUBSCRIBERS:

        return ChannelMomentumEvaluation(None, DIAG_SUBSCRIBER_UNAVAILABLE)



    title = title_by_channel.get(channel_id, channel_entity.title if channel_entity else channel_id)

    all_recent = [v for v in videos if _in_window(v.published_at, recent_start, end)]

    all_previous = [v for v in videos if _in_window(v.published_at, previous_start, recent_start)]



    recent_eligible = [

        v

        for v in all_recent

        if _eligible_channel_video(bundle, v, publishable_confirmed_ids=publishable_confirmed_ids)

    ]

    previous_eligible = [

        v

        for v in all_previous

        if _eligible_channel_video(bundle, v, publishable_confirmed_ids=publishable_confirmed_ids)

    ]



    incompleteness: list[str] = []

    format_blocked_recent = sum(

        1

        for v in all_recent

        if _format_gate_failure(bundle, v, publishable_confirmed_ids=publishable_confirmed_ids)

        == DIAG_FORMAT_NOT_CONFIRMED

    )

    format_blocked_previous = sum(

        1

        for v in all_previous

        if _format_gate_failure(bundle, v, publishable_confirmed_ids=publishable_confirmed_ids)

        == DIAG_FORMAT_NOT_CONFIRMED

    )

    if format_blocked_recent:

        incompleteness.append(f"{format_blocked_recent} recent in DB without confirmed regular format")

    if format_blocked_previous:

        incompleteness.append(f"{format_blocked_previous} previous in DB without confirmed regular format")



    if len(recent_eligible) < MIN_RECENT_VIDEOS:

        return ChannelMomentumEvaluation(None, DIAG_INSUFFICIENT_RECENT_ELIGIBLE)

    if len(all_previous) < MIN_PREVIOUS_VIDEOS and len(previous_eligible) < MIN_PREVIOUS_VIDEOS:

        incompleteness.append("fewer than 2 previous-window videos in DB for this channel")

        return ChannelMomentumEvaluation(None, DIAG_INSUFFICIENT_PREVIOUS_IN_WINDOW)



    previous_measurable: list[AgeAlignedVphMeasurement] = []

    recent_measurable: list[AgeAlignedVphMeasurement] = []

    missing_prev_snap = 0

    missing_recent_snap = 0

    for v in previous_eligible:

        m = _measure_video(bundle, v, horizon_hours=horizon, tolerance_hours=tolerance)

        if m is None:

            missing_prev_snap += 1

        else:

            previous_measurable.append(m)

    for v in recent_eligible:

        m = _measure_video(bundle, v, horizon_hours=horizon, tolerance_hours=tolerance)

        if m is None:

            missing_recent_snap += 1

        else:

            recent_measurable.append(m)



    if missing_prev_snap:

        incompleteness.append(

            f"{missing_prev_snap} previous eligible without snapshot near {int(horizon)}h "

            f"(±{tolerance}h) from publish",

        )

    if missing_recent_snap:

        incompleteness.append(

            f"{missing_recent_snap} recent eligible without snapshot near {int(horizon)}h "

            f"(±{tolerance}h) from publish",

        )



    if len(previous_measurable) < MIN_PREVIOUS_VIDEOS:

        return ChannelMomentumEvaluation(None, DIAG_INSUFFICIENT_MEASURABLE_PREVIOUS)

    if len(recent_measurable) < MIN_RECENT_VIDEOS:

        return ChannelMomentumEvaluation(None, DIAG_INSUFFICIENT_MEASURABLE_RECENT)



    prev_vph = [m.vph for m in previous_measurable]

    previous_median = float(median(prev_vph))

    if previous_median <= 0:

        incompleteness.append("previous-window median VPH at horizon is zero; ratio not computed")

        row = _build_row(

            channel_id=channel_id,

            title=title,

            latest_subs=latest_subs,

            videos=videos,

            recent_eligible=recent_eligible,

            previous_eligible=previous_eligible,

            recent_measurable=recent_measurable,

            previous_measurable=previous_measurable,

            previous_median=0.0,

            recent_improvement_count=0,

            ratio=None,

            previous_baseline_zero=True,

            publishable_confirmed_ids=publishable_confirmed_ids,

            bundle=bundle,

            config=config,

            end=end,

            lookback_start=lookback_start,

            incompleteness=incompleteness,

            signal_published=False,

        )

        return ChannelMomentumEvaluation(row, DIAG_ZERO_PREVIOUS_BASELINE)



    improving = [m for m in recent_measurable if m.vph >= ratio_threshold * previous_median]

    recent_improvement_count = len(improving)

    recent_median = float(median(m.vph for m in recent_measurable))

    ratio = round(recent_median / previous_median, 4) if previous_median > 0 else None



    signal_published = recent_improvement_count >= MIN_IMPROVING_RECENT

    primary = None if signal_published else DIAG_INSUFFICIENT_REPEATED_IMPROVEMENT



    row = _build_row(

        channel_id=channel_id,

        title=title,

        latest_subs=latest_subs,

        videos=videos,

        recent_eligible=recent_eligible,

        previous_eligible=previous_eligible,

        recent_measurable=recent_measurable,

        previous_measurable=previous_measurable,

        previous_median=previous_median,

        recent_improvement_count=recent_improvement_count,

        ratio=ratio,

        previous_baseline_zero=False,

        publishable_confirmed_ids=publishable_confirmed_ids,

        bundle=bundle,

        config=config,

        end=end,

        lookback_start=lookback_start,

        incompleteness=incompleteness,

        signal_published=signal_published,

    )

    return ChannelMomentumEvaluation(row if signal_published else None, primary)





def _build_row(

    *,

    channel_id: str,

    title: str,

    latest_subs: int,

    videos: list[Video],

    recent_eligible: list[Video],

    previous_eligible: list[Video],

    recent_measurable: list[AgeAlignedVphMeasurement],

    previous_measurable: list[AgeAlignedVphMeasurement],

    previous_median: float,

    recent_improvement_count: int,

    ratio: float | None,

    previous_baseline_zero: bool,

    publishable_confirmed_ids: frozenset[str] | None,

    bundle: AttentionEvidenceBundle,

    config: AttentionEngineConfig,

    end: datetime,

    lookback_start: datetime,

    incompleteness: list[str],

    signal_published: bool,

) -> ChannelMomentum:

    horizon = int(config.channel_momentum_horizon_hours)

    tolerance = float(config.channel_momentum_horizon_tolerance_hours)

    ratio_threshold = float(config.channel_momentum_improvement_ratio)

    recent_median = float(median(m.vph for m in recent_measurable)) if recent_measurable else None



    breakout_n = sum(1 for vid in recent_eligible if _breakout_eligible(bundle, vid))

    confirmed_n = 0

    for vid in recent_eligible:

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

    improving_ids = {m.video_id for m in recent_measurable if m.vph >= ratio_threshold * previous_median}

    ranked_recent = sorted(

        recent_measurable,

        key=lambda m: (-m.vph, m.video_id),

    )

    representative = tuple(m.video_id for m in ranked_recent if m.video_id in improving_ids)[:5]

    if not representative:

        representative = tuple(m.video_id for m in ranked_recent[:5])



    codes: list[str] = []

    humans: list[str] = []

    if signal_published:

        codes.append(REASON_REPEATED_AGE_ALIGNED_IMPROVEMENT)

        humans.append(

            f"{recent_improvement_count} recent videos at ~{horizon}h (±{tolerance}h) each ≥ "

            f"{ratio_threshold}× previous median {previous_median:.1f} VPH",

        )

        codes.append(REASON_CONTENT_MOMENTUM)

        humans.append(

            f"Age-aligned samples: {len(recent_measurable)}/{len(recent_eligible)} recent, "

            f"{len(previous_measurable)}/{len(previous_eligible)} previous "

            f"(windows {config.channel_recent_days}d / {config.channel_previous_days}d)",

        )



    if breakout_n:

        codes.append(REASON_CONTEXT_BREAKOUT_ELIGIBLE)

        humans.append(f"Context: {breakout_n} recent videos qualify for Breakout analysis")

    if confirmed_n:

        codes.append(REASON_CONTEXT_KEYWORD_72H_GROWTH)

        humans.append(

            f"Context: {confirmed_n} recent videos with any positive keyword-hit 72h view delta "

            f"(not the {horizon}h publish horizon)",

        )

    if growth_ok and growth_abs is not None and growth_abs > 0:

        codes.append(REASON_CONTEXT_SUBSCRIBER_GROWTH)

        humans.append(

            f"Context: ChannelSnapshot +{growth_abs} subscribers ({growth_pct:.1f}%) across observation windows",

        )



    if incompleteness:

        humans.append("Incomplete history: " + "; ".join(incompleteness))



    notes = tuple(incompleteness)

    return ChannelMomentum(

        channel_id=channel_id,

        channel_title=title,

        subscriber_count_latest=latest_subs,

        observed_video_count=len(videos),

        recent_video_count=len(recent_eligible),

        previous_video_count=len(previous_eligible),

        breakout_video_count=breakout_n,

        confirmed_72h_count=confirmed_n,

        recent_median_vph=recent_median,

        previous_median_vph=previous_median if previous_measurable else None,

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

        momentum_horizon_hours=horizon,

        momentum_horizon_tolerance_hours=tolerance,

        recent_eligible_count=len(recent_eligible),

        previous_eligible_count=len(previous_eligible),

        recent_measurable_count=len(recent_measurable),

        previous_measurable_count=len(previous_measurable),

        recent_improvement_count=recent_improvement_count,

        improvement_ratio_threshold=ratio_threshold,

        previous_baseline_zero=previous_baseline_zero,

        incompleteness_notes=notes,

    )





def build_channel_momentum(

    bundle: AttentionEvidenceBundle,

    config: AttentionEngineConfig,

    *,

    now: datetime,

    publishable_confirmed_ids: frozenset[str] | None = None,

) -> list[ChannelMomentum]:

    rows: list[ChannelMomentum] = []

    for channel_id, videos in bundle.extra_channel_videos.items():

        evaluation = evaluate_channel_momentum(

            bundle,

            config,

            channel_id=channel_id,

            videos=videos,

            now=now,

            publishable_confirmed_ids=publishable_confirmed_ids,

        )

        if evaluation.momentum is not None:

            rows.append(evaluation.momentum)



    def sort_key(item: ChannelMomentum) -> tuple:

        ratio = item.recent_median_vph_vs_previous

        ratio_sort = -(ratio) if ratio is not None else 0.0

        return (

            -item.recent_improvement_count,

            ratio_sort,

            -item.recent_measurable_count,

            item.channel_id,

        )



    rows.sort(key=sort_key)

    return rows[: config.channel_limit]





def diagnose_channel_momentum_candidates(

    bundle: AttentionEvidenceBundle,

    config: AttentionEngineConfig,

    *,

    now: datetime,

    publishable_confirmed_ids: frozenset[str] | None = None,

) -> list[tuple[str, str | None]]:

    """Return (channel_id, primary_diagnostic) for every channel in the lookback universe."""

    out: list[tuple[str, str | None]] = []

    for channel_id, videos in bundle.extra_channel_videos.items():

        evaluation = evaluate_channel_momentum(

            bundle,

            config,

            channel_id=channel_id,

            videos=videos,

            now=now,

            publishable_confirmed_ids=publishable_confirmed_ids,

        )

        out.append((channel_id, evaluation.primary_diagnostic))

    return out


