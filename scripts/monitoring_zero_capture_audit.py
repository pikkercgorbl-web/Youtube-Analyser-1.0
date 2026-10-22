#!/usr/bin/env python3
"""Read-only monitoring zero-capture diagnostic (local DB). No writes, no API."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv
from sqlalchemy import func, select

from app.models.db import SessionLocal
from app.models.orm import (
    Channel,
    KeywordDiscoveryHit,
    MonitoringCycleRun,
    MonitoringVideoQueueEntry,
    Video,
    VideoFormatEnrichmentAttempt,
    VideoSnapshot,
)
from app.services.channel_momentum_age_vph import select_age_aligned_measurement
from app.services.historical_video_format_verification import OUTCOME_CONFIRMED_REGULAR
from app.services.metrics import ensure_utc, utc_now
from app.services.monitoring_cycle import (
    _budget_context,
    _count_cap_exclusions,
    _plan_and_requests_for_decision,
    _state_to_tier_input,
    _tier_counts,
)
from app.services.monitoring_radar_eligibility import monitoring_video_eligible
from app.services.monitoring_tier_budget_policy import (
    ApiBudgetPolicy,
    MonitoringTier,
    MonitoringTierPolicy,
    allocate_capture_budget,
    apply_channel_active_cap,
    apply_global_monitoring_cap,
    assign_monitoring_tiers,
    snapshot_collection_policy_for_tier,
)
from app.services.monitoring_video_source import load_monitored_video_states
from app.services.snapshot_measurement import derive_latest_measurement
from app.services.video_published_at import PUBLISHED_AT_SOURCE_API, published_at_source_rank
from app.services.video_snapshot_storage import derive_snapshot_metrics
from app.services.radar_target_eligibility import (
    RADAR_MAX_CHANNEL_SUBSCRIBERS,
    radar_target_eligible,
    radar_target_rejection_reason,
    resolve_known_subscribers,
)
from app.services.snapshot_collection_policy import (
    build_capture_requests,
    compute_video_age_hours,
    existing_snapshot_from_orm,
    load_snapshots_by_video_id,
    plan_video_revisits,
)
from app.services.video_format_api_verification import load_api_format_confirmed_video_ids
from app.services.video_snapshot_storage import get_latest_snapshots_for_videos

OUT_PATH = ROOT / "artifacts" / "monitoring_zero_capture_audit.json"


def _diag_cycle_at(session, at: datetime) -> dict[str, Any]:
    tier_cfg = MonitoringTierPolicy()
    budget_cfg = ApiBudgetPolicy()
    states = load_monitored_video_states(session, now=at)
    state_by_id = {r.video_id: r for r in states}
    tier_inputs = [_state_to_tier_input(row) for row in states]
    all_decisions = assign_monitoring_tiers(tier_inputs, tier_cfg)

    tier_unmonitored = Counter(
        d.excluded_reason or "unknown"
        for d in all_decisions
        if d.tier == MonitoringTier.UNMONITORED
    )
    load_filtered = len(states)
    candidates_sql = sum(1 for _ in [])  # filled below

    channel_cap = apply_channel_active_cap(all_decisions, tier_cfg.max_active_videos_per_channel)
    global_cap = apply_global_monitoring_cap(channel_cap.retained, budget_cfg.max_active_monitored_videos)
    channel_excl = _count_cap_exclusions(channel_cap.excluded, "channel_active_cap")
    global_excl = _count_cap_exclusions(global_cap.excluded, "global_monitoring_cap")

    active = list(global_cap.retained)
    video_ids = [d.video_id for d in active]
    snapshots_by_video_id = load_snapshots_by_video_id(session, video_ids)

    due_total = overdue_total = 0
    checkpoint_status_counts: Counter[str] = Counter()
    contexts = []
    all_requests = []

    for decision in active:
        plan, requests = _plan_and_requests_for_decision(
            decision,
            state_by_id=state_by_id,
            snapshots_by_video_id=snapshots_by_video_id,
            current_time=at,
            tier_policy=tier_cfg,
            run_id="audit",
        )
        for cp in plan.checkpoints:
            checkpoint_status_counts[cp.status] += 1
        for cp in plan.due_checkpoints:
            if cp.status == "due":
                due_total += 1
            elif cp.status == "overdue":
                overdue_total += 1
        for request in requests:
            contexts.append(_budget_context(request, decision=decision, plan=plan))
        all_requests.extend(requests)

    budget = allocate_capture_budget(contexts, budget_cfg)
    zero_capture_reason = None
    if due_total == 0 and overdue_total == 0:
        zero_capture_reason = "no_due_or_overdue_checkpoints_in_active_pool"
    elif budget.selected_for_capture_count == 0 and (due_total + overdue_total) > 0:
        zero_capture_reason = "budget_deferred_all_capture_requests"
    elif budget.selected_for_capture_count == 0:
        zero_capture_reason = "no_capture_requests_built"

    return {
        "at_utc": at.isoformat(),
        "loaded_eligible_unmonitored": {
            "loaded": load_filtered,
            "eligible_active_tier": len(active),
            "unmonitored": load_filtered - len(active),
        },
        "exclusion_breakdown": {
            "not_loaded_radar_monitoring_filter": "see per_video_funnel; SQL candidate pool > loaded",
            "tier_unmonitored_among_loaded": dict(tier_unmonitored),
            "channel_active_cap": channel_excl,
            "global_monitoring_cap": global_excl,
        },
        "tier_counts": _tier_counts(active),
        "due": due_total,
        "overdue": overdue_total,
        "capture_requests_built": len(all_requests),
        "selected": budget.selected_for_capture_count,
        "deferred": budget.deferred_count,
        "checkpoint_status_counts_active_pool": dict(checkpoint_status_counts),
        "inferred_zero_capture_reason": zero_capture_reason,
    }


def _next_future_checkpoint(session, at: datetime) -> dict[str, Any] | None:
    tier_cfg = MonitoringTierPolicy()
    budget_cfg = ApiBudgetPolicy()
    states = load_monitored_video_states(session, now=at)
    state_by_id = {r.video_id: r for r in states}
    decisions = assign_monitoring_tiers([_state_to_tier_input(s) for s in states], tier_cfg)
    channel_cap = apply_channel_active_cap(decisions, tier_cfg.max_active_videos_per_channel)
    global_cap = apply_global_monitoring_cap(channel_cap.retained, budget_cfg.max_active_monitored_videos)
    active = list(global_cap.retained)
    snapshots = load_snapshots_by_video_id(session, [d.video_id for d in active])

    best: tuple[datetime, str, int, float] | None = None
    for d in active:
        st = state_by_id[d.video_id]
        policy = snapshot_collection_policy_for_tier(d.tier, tier_cfg)
        plan = plan_video_revisits(
            video_id=d.video_id,
            published_at=st.published_at,
            existing_snapshots=snapshots.get(d.video_id, []),
            current_time=at,
            channel_id=st.channel_id,
            content_format=st.content_format,
            is_short=st.is_short,
            is_live=st.is_live,
            policy=policy,
        )
        if plan.current_age_hours is None or st.published_at is None:
            continue
        for cp in plan.checkpoints:
            if cp.status != "pending":
                continue
            due_at = ensure_utc(st.published_at) + timedelta(hours=float(cp.target_age_hours))
            if due_at <= at:
                continue
            if best is None or due_at < best[0]:
                best = (due_at, d.video_id, cp.target_age_hours, plan.current_age_hours)

    if best is None:
        return None
    due_at, vid, cp_h, age_h = best
    return {
        "video_id": vid,
        "checkpoint_hours": cp_h,
        "due_at_utc": due_at.isoformat(),
        "hours_until_due": round((due_at - ensure_utc(at)).total_seconds() / 3600.0, 4),
        "current_age_hours": age_h,
    }


def _funnel_24h(session, now: datetime) -> dict[str, Any]:
    since = now - timedelta(hours=24)
    hits = list(
        session.scalars(
            select(KeywordDiscoveryHit)
            .where(KeywordDiscoveryHit.discovered_at >= since)
            .order_by(KeywordDiscoveryHit.discovered_at.desc()),
        ).all(),
    )
    by_video: dict[str, KeywordDiscoveryHit] = {}
    for h in hits:
        if h.video_id not in by_video:
            by_video[h.video_id] = h

    video_ids = list(by_video.keys())
    videos = {
        v.id: v
        for v in session.scalars(select(Video).where(Video.id.in_(video_ids))).all()
    } if video_ids else {}
    channel_ids = list({v.channel_id for v in videos.values() if v.channel_id})
    channels = {
        c.id: c
        for c in session.scalars(select(Channel).where(Channel.id.in_(channel_ids))).all()
    } if channel_ids else {}
    latest = get_latest_snapshots_for_videos(session, video_ids) if video_ids else {}
    confirmed = load_api_format_confirmed_video_ids(session, video_ids) if video_ids else frozenset()

    stage_known_subs: set[str] = set()
    stage_confirmed: set[str] = set()
    stage_monitoring_load: set[str] = set()
    stage_active: set[str] = set()
    stage_due_or_overdue: set[str] = set()

    rejection_at_subs: Counter[str] = Counter()
    rejection_at_monitoring: Counter[str] = Counter()

    tier_cfg = MonitoringTierPolicy()
    budget_cfg = ApiBudgetPolicy()

    for vid, hit in by_video.items():
        video = videos.get(vid)
        if not video:
            continue
        ch = channels.get(video.channel_id)
        snap = latest.get(vid)
        reason = radar_target_rejection_reason(
            content_format=video.content_format,
            channel=ch,
            latest_snapshot=snap,
        )
        subs = resolve_known_subscribers(channel=ch, latest_snapshot=snap)
        if reason is None and subs is not None and subs <= RADAR_MAX_CHANNEL_SUBSCRIBERS:
            stage_known_subs.add(vid)
        elif reason:
            rejection_at_subs[reason] += 1

        if vid in confirmed:
            stage_confirmed.add(vid)

        if monitoring_video_eligible(
            video=video,
            channel=ch,
            latest_snapshot=snap,
            confirmed_regular_ids=confirmed,
        ):
            stage_monitoring_load.add(vid)
        else:
            if not radar_target_eligible(video=video, channel=ch, latest_snapshot=snap):
                rejection_at_monitoring["radar_target_ineligible"] += 1
            elif video.id not in confirmed:
                rejection_at_monitoring["not_confirmed_regular"] += 1
            else:
                rejection_at_monitoring["other_monitoring_filter"] += 1

    states = load_monitored_video_states(session, now=now)
    state_by_id = {s.video_id: s for s in states}
    decisions = assign_monitoring_tiers([_state_to_tier_input(s) for s in states], tier_cfg)
    channel_cap = apply_channel_active_cap(decisions, tier_cfg.max_active_videos_per_channel)
    global_cap = apply_global_monitoring_cap(channel_cap.retained, budget_cfg.max_active_monitored_videos)
    active_ids = {d.video_id for d in global_cap.retained}
    snapshots = load_snapshots_by_video_id(session, list(active_ids))

    for d in global_cap.retained:
        if d.video_id not in by_video:
            continue
        stage_active.add(d.video_id)
        st = state_by_id[d.video_id]
        policy = snapshot_collection_policy_for_tier(d.tier, tier_cfg)
        plan = plan_video_revisits(
            video_id=d.video_id,
            published_at=st.published_at,
            existing_snapshots=snapshots.get(d.video_id, []),
            current_time=now,
            channel_id=st.channel_id,
            content_format=st.content_format,
            is_short=st.is_short,
            is_live=st.is_live,
            policy=policy,
        )
        if plan.due_checkpoints:
            stage_due_or_overdue.add(d.video_id)

    pub_ages = []
    disc_ages = []
    for vid, hit in by_video.items():
        video = videos.get(vid)
        if not video or not video.published_at:
            continue
        pub_age = compute_video_age_hours(video.published_at, now)
        disc_age = (now - ensure_utc(hit.discovered_at)).total_seconds() / 3600.0
        if pub_age is not None:
            pub_ages.append(pub_age)
        disc_ages.append(disc_age)

    return {
        "window_start_utc": since.isoformat(),
        "window_end_utc": now.isoformat(),
        "discovery_hits_rows": len(hits),
        "unique_video_ids_discovered": len(by_video),
        "stage_counts": {
            "1_discovery_unique": len(by_video),
            "2_known_subscribers_lte_100k": len(stage_known_subs),
            "3_confirmed_regular": len(stage_confirmed),
            "4_monitoring_load_eligible": len(stage_monitoring_load),
            "5_active_tier_after_caps": len(stage_active & set(by_video.keys())),
            "6_has_due_or_overdue_checkpoint": len(stage_due_or_overdue),
        },
        "rejections_known_subs_gate": dict(rejection_at_subs),
        "rejections_monitoring_gate": dict(rejection_at_monitoring),
        "age_hours_discovery_median": round(sorted(disc_ages)[len(disc_ages) // 2], 2) if disc_ages else None,
        "age_hours_since_publication_median": round(sorted(pub_ages)[len(pub_ages) // 2], 2) if pub_ages else None,
    }


def _explain_video_monitoring(session, video_id: str, now: datetime) -> dict[str, Any]:
    video = session.get(Video, video_id)
    if not video:
        return {"video_id": video_id, "error": "video_not_found"}
    ch = session.get(Channel, video.channel_id) if video.channel_id else None
    latest = get_latest_snapshots_for_videos(session, [video_id]).get(video_id)
    confirmed = load_api_format_confirmed_video_ids(session, [video_id])
    tier_cfg = MonitoringTierPolicy()
    budget_cfg = ApiBudgetPolicy()

    steps: list[dict[str, Any]] = []

    r_reason = radar_target_rejection_reason(
        content_format=video.content_format,
        channel=ch,
        latest_snapshot=latest,
    )
    subs = resolve_known_subscribers(channel=ch, latest_snapshot=latest)
    steps.append(
        {
            "step": "radar_known_subscribers_lte_100k",
            "pass": r_reason is None and subs is not None and subs <= RADAR_MAX_CHANNEL_SUBSCRIBERS,
            "detail": {"rejection": r_reason, "subscribers": subs},
        },
    )
    steps.append(
        {
            "step": "confirmed_regular",
            "pass": video_id in confirmed,
            "detail": {"content_format": str(video.content_format)},
        },
    )
    mon_ok = monitoring_video_eligible(
        video=video,
        channel=ch,
        latest_snapshot=latest,
        confirmed_regular_ids=confirmed,
    )
    steps.append({"step": "monitoring_load", "pass": mon_ok})

    in_loaded = any(s.video_id == video_id for s in load_monitored_video_states(session, now=now))
    steps.append({"step": "in_load_monitored_video_states", "pass": in_loaded})

    capture_outcome = "not_in_active_pool"
    plan_summary = None
    if in_loaded:
        states = load_monitored_video_states(session, now=now)
        st = next(s for s in states if s.video_id == video_id)
        decs = assign_monitoring_tiers([_state_to_tier_input(st)], tier_cfg)
        all_decs = assign_monitoring_tiers([_state_to_tier_input(s) for s in states], tier_cfg)
        channel_cap = apply_channel_active_cap(all_decs, tier_cfg.max_active_videos_per_channel)
        global_cap = apply_global_monitoring_cap(channel_cap.retained, budget_cfg.max_active_monitored_videos)
        active_map = {d.video_id: d for d in global_cap.retained}
        if video_id not in active_map:
            for ex in channel_cap.excluded:
                if ex.video_id == video_id:
                    capture_outcome = f"excluded_channel_cap:{ex.excluded_reason}"
                    break
            else:
                for ex in global_cap.excluded:
                    if ex.video_id == video_id:
                        capture_outcome = f"excluded_global_cap:{ex.excluded_reason}"
                        break
                else:
                    d0 = next(d for d in all_decs if d.video_id == video_id)
                    if d0.tier == MonitoringTier.UNMONITORED:
                        capture_outcome = f"tier_unmonitored:{d0.excluded_reason}"
                    else:
                        capture_outcome = "not_retained_unknown"
        else:
            d = active_map[video_id]
            snaps = load_snapshots_by_video_id(session, [video_id])
            policy = snapshot_collection_policy_for_tier(d.tier, tier_cfg)
            plan = plan_video_revisits(
                video_id=video_id,
                published_at=st.published_at,
                existing_snapshots=snaps.get(video_id, []),
                current_time=now,
                channel_id=st.channel_id,
                content_format=st.content_format,
                is_short=st.is_short,
                is_live=st.is_live,
                policy=policy,
            )
            reqs = build_capture_requests(plan, requested_at=now, source="monitoring_worker")
            plan_summary = {
                "tier": d.tier.value,
                "monitoring_status": plan.monitoring_status,
                "stop_reason": plan.stop_reason,
                "checkpoints": [
                    {"h": cp.target_age_hours, "status": cp.status}
                    for cp in plan.checkpoints
                ],
                "due_checkpoints": [cp.target_age_hours for cp in plan.due_checkpoints],
                "next_checkpoint_hours": plan.next_checkpoint_hours,
            }
            if not plan.due_checkpoints:
                capture_outcome = "active_but_no_due_or_overdue_checkpoint"
            else:
                capture_outcome = "would_request_capture_this_cycle"

    pub_age = (
        compute_video_age_hours(video.published_at, now)
        if video.published_at
        else None
    )
    return {
        "video_id": video_id,
        "published_at": video.published_at.isoformat() if video.published_at else None,
        "age_hours_since_publication": pub_age,
        "steps": steps,
        "capture_outcome": capture_outcome,
        "plan": plan_summary,
    }


def _cohort_735_monitoring_load_ids(session, now: datetime) -> tuple[set[str], dict[str, KeywordDiscoveryHit]]:
    """24h discovery videos that pass subs + confirmed_regular + monitoring_video_eligible."""
    since = now - timedelta(hours=24)
    hits = list(
        session.scalars(
            select(KeywordDiscoveryHit).where(KeywordDiscoveryHit.discovered_at >= since),
        ).all(),
    )
    by_video: dict[str, KeywordDiscoveryHit] = {}
    for h in hits:
        if h.video_id not in by_video:
            by_video[h.video_id] = h
    if not by_video:
        return set(), by_video

    video_ids = list(by_video.keys())
    videos = {
        v.id: v
        for v in session.scalars(select(Video).where(Video.id.in_(video_ids))).all()
    }
    channel_ids = list({v.channel_id for v in videos.values() if v.channel_id})
    channels = {
        c.id: c
        for c in session.scalars(select(Channel).where(Channel.id.in_(channel_ids))).all()
    }
    latest = get_latest_snapshots_for_videos(session, video_ids)
    confirmed = load_api_format_confirmed_video_ids(session, video_ids)

    cohort: set[str] = set()
    for vid in by_video:
        video = videos.get(vid)
        if not video:
            continue
        ch = channels.get(video.channel_id)
        if not monitoring_video_eligible(
            video=video,
            channel=ch,
            latest_snapshot=latest.get(vid),
            confirmed_regular_ids=confirmed,
        ):
            continue
        cohort.add(vid)
    return cohort, by_video


def _cohort_active_tier_reasons(session, now: datetime) -> dict[str, Any]:
    cohort, _ = _cohort_735_monitoring_load_ids(session, now)
    tier_cfg = MonitoringTierPolicy()
    budget_cfg = ApiBudgetPolicy()
    states = load_monitored_video_states(session, now=now)
    state_by_id = {s.video_id: s for s in states}
    decisions = assign_monitoring_tiers([_state_to_tier_input(s) for s in states], tier_cfg)
    decision_by_id = {d.video_id: d for d in decisions}
    channel_cap = apply_channel_active_cap(decisions, tier_cfg.max_active_videos_per_channel)
    global_cap = apply_global_monitoring_cap(channel_cap.retained, budget_cfg.max_active_monitored_videos)
    active_ids = {d.video_id for d in global_cap.retained}

    excluded_channel = {d.video_id: d.excluded_reason for d in channel_cap.excluded}
    excluded_global = {d.video_id: d.excluded_reason for d in global_cap.excluded}

    reasons: Counter[str] = Counter()
    not_in_loaded: list[str] = []

    for vid in cohort:
        if vid not in state_by_id:
            not_in_loaded.append(vid)
            reasons["not_in_load_monitored_video_states"] += 1
            continue
        if vid in active_ids:
            reasons["active_tier"] += 1
            continue
        d = decision_by_id.get(vid)
        if d and d.tier == MonitoringTier.UNMONITORED:
            reasons[d.excluded_reason or "tier_unmonitored"] += 1
            continue
        if vid in excluded_channel:
            reasons["channel_active_cap"] += 1
            continue
        if vid in excluded_global:
            reasons["global_monitoring_cap"] += 1
            continue
        reasons["eligible_but_not_retained_unknown"] += 1

    missing_vph_in_cohort = sum(
        1
        for vid in cohort
        if (st := state_by_id.get(vid)) is not None and st.raw_vph is None
    )
    return {
        "cohort_size_monitoring_load_24h": len(cohort),
        "active_tier_count": reasons.get("active_tier", 0),
        "inactive_reason_counts": {k: v for k, v in reasons.items() if k != "active_tier"},
        "cohort_still_missing_vph_after_discovery_bootstrap": missing_vph_in_cohort,
        "not_in_loaded_sample": not_in_loaded[:5],
    }


def _trace_vph_bootstrap(session, video_id: str) -> dict[str, Any]:
    video = session.get(Video, video_id)
    if not video:
        return {"video_id": video_id, "error": "video_not_found"}
    hits = list(
        session.scalars(
            select(KeywordDiscoveryHit)
            .where(KeywordDiscoveryHit.video_id == video_id)
            .order_by(KeywordDiscoveryHit.discovered_at.asc()),
        ).all(),
    )
    latest = get_latest_snapshots_for_videos(session, [video_id]).get(video_id)
    snap_count = session.scalar(
        select(func.count()).select_from(VideoSnapshot).where(VideoSnapshot.video_id == video_id),
    )

    measurement = derive_latest_measurement(
        video=video,
        latest_snapshot=latest,
        discovery_hits=hits,
    )
    load_state = next((s for s in load_monitored_video_states(session) if s.video_id == video_id), None)

    branch = "unavailable"
    branch_detail: dict[str, Any] = {}
    if latest is not None:
        branch = "snapshot_path"
        pub, approx = measurement.published_at_used, measurement.published_at_approximate
        age, vph, _ = derive_snapshot_metrics(
            views=latest.views,
            published_at=pub,
            captured_at=latest.captured_at,
            subscribers=None,
        )
        branch_detail = {
            "snapshot_id": latest.id,
            "snapshot_views": latest.views,
            "snapshot_captured_at": latest.captured_at.isoformat() if latest.captured_at else None,
            "derived_age_hours": age,
            "derived_vph": vph,
            "published_at_approximate": approx,
        }
    elif hits:
        usable = [
            h
            for h in hits
            if h.views_at_discovery is not None and h.views_at_discovery >= 0 and h.discovered_at
        ]
        if usable:
            branch = "discovery_path"
            hit = usable[0]
            pub, approx = measurement.published_at_used, measurement.published_at_approximate
            age, vph, _ = derive_snapshot_metrics(
                views=int(hit.views_at_discovery),
                published_at=pub,
                captured_at=hit.discovered_at,
                subscribers=None,
            )
            branch_detail = {
                "earliest_hit_discovered_at": hit.discovered_at.isoformat(),
                "views_at_discovery": hit.views_at_discovery,
                "derived_age_hours": age,
                "derived_vph": vph,
                "published_at_approximate": approx,
            }
        else:
            branch = "discovery_hits_present_but_unusable"
            branch_detail = {
                "hits_count": len(hits),
                "sample_views_at_discovery": [h.views_at_discovery for h in hits[:3]],
            }
    else:
        branch_detail = {
            "note": "Video.views_count is never used for monitoring VPH",
            "video_views_count": video.views_count,
        }

    vph_none_reason = None
    if measurement.average_vph is None:
        if branch == "unavailable":
            vph_none_reason = "derive_latest_measurement_source_unavailable"
        elif branch == "discovery_hits_present_but_unusable":
            vph_none_reason = "no_usable_views_at_discovery_on_hits"
        elif branch_detail.get("derived_age_hours") is None or branch_detail.get("derived_age_hours") <= 0:
            vph_none_reason = "derive_snapshot_metrics_invalid_age_non_positive"
        elif branch_detail.get("snapshot_views") is None and branch != "discovery_path":
            vph_none_reason = "missing_views_at_measurement_time"
        else:
            vph_none_reason = "derive_snapshot_metrics_other"

    earliest_hit = hits[0] if hits else None
    return {
        "video_id": video_id,
        "video_views_count": video.views_count,
        "published_at": video.published_at.isoformat() if video.published_at else None,
        "published_at_source": getattr(video, "published_at_source", None),
        "api_published_at_rank_ok": (
            published_at_source_rank(getattr(video, "published_at_source", None))
            >= published_at_source_rank(PUBLISHED_AT_SOURCE_API)
            if video.published_at
            else False
        ),
        "keyword_discovery_hit": (
            None
            if earliest_hit is None
            else {
                "discovered_at": earliest_hit.discovered_at.isoformat(),
                "views_at_discovery": earliest_hit.views_at_discovery,
                "vph_at_discovery": earliest_hit.vph_at_discovery,
            }
        ),
        "format_enrichment_stores_views": False,
        "snapshot_count": int(snap_count or 0),
        "latest_snapshot_id": latest.id if latest else None,
        "measurement_source": measurement.source,
        "measurement_average_vph": measurement.average_vph,
        "load_monitored_video_states_raw_vph": load_state.raw_vph if load_state else None,
        "bootstrap_branch": branch,
        "bootstrap_branch_detail": branch_detail,
        "vph_none_reason": vph_none_reason,
    }


def _missing_vph_samples_from_cohort(session, now: datetime, limit: int = 10) -> list[dict]:
    cohort, _ = _cohort_735_monitoring_load_ids(session, now)
    states = load_monitored_video_states(session, now=now)
    missing = [s.video_id for s in states if s.video_id in cohort and s.raw_vph is None]
    # Prefer cohort members with confirmed_regular but no vph
    if len(missing) < limit:
        for vid in sorted(cohort):
            if vid not in missing:
                st = next((s for s in states if s.video_id == vid), None)
                if st is None or st.raw_vph is None:
                    missing.append(vid)
            if len(missing) >= limit:
                break
    return [_trace_vph_bootstrap(session, vid) for vid in missing[:limit]]


def _fulfilled_late_audit(session, video_id: str, now: datetime) -> dict[str, Any]:
    video = session.get(Video, video_id)
    if not video or not video.published_at:
        return {"video_id": video_id, "error": "missing_video_or_published_at"}
    snaps = list(
        session.scalars(
            select(VideoSnapshot)
            .where(VideoSnapshot.video_id == video_id)
            .order_by(VideoSnapshot.captured_at.asc()),
        ).all(),
    )
    existing = [existing_snapshot_from_orm(s) for s in snaps]
    plan = plan_video_revisits(
        video_id=video_id,
        published_at=video.published_at,
        existing_snapshots=existing,
        current_time=now,
        content_format="regular",
    )
    momentum_24 = select_age_aligned_measurement(
        video_id=video_id,
        published_at=video.published_at,
        snapshots=snaps,
        horizon_hours=24,
        tolerance_hours=6,
    )
    per_snap = []
    for s in snaps:
        meta = s.raw_metadata if isinstance(s.raw_metadata, dict) else {}
        cp = meta.get("checkpoint_age_hours")
        per_snap.append(
            {
                "snapshot_id": s.id,
                "captured_at": s.captured_at.isoformat() if s.captured_at else None,
                "age_hours": s.age_hours,
                "source": s.source,
                "fetch_status": s.fetch_status,
                "checkpoint_age_hours_meta": cp,
                "capture_reason_meta": meta.get("capture_reason"),
            },
        )
    cp_rows = []
    for cp in plan.checkpoints:
        cp_rows.append(
            {
                "target_hours": cp.target_age_hours,
                "status": cp.status,
                "matched_snapshot_id": cp.matched_snapshot_id,
                "matched_age_hours": cp.matched_snapshot_age_hours,
            },
        )
    violations = []
    for cp in plan.checkpoints:
        if cp.status != "fulfilled_late" or cp.matched_snapshot_id is None:
            continue
        snap = next((s for s in snaps if s.id == cp.matched_snapshot_id), None)
        if snap is None:
            violations.append(f"fulfilled_late_cp{cp.target_age_hours}_missing_snap")
            continue
        meta = snap.raw_metadata if isinstance(snap.raw_metadata, dict) else {}
        meta_cp = meta.get("checkpoint_age_hours")
        try:
            meta_cp_int = int(meta_cp) if meta_cp is not None else None
        except (TypeError, ValueError):
            meta_cp_int = None
        if meta_cp_int != cp.target_age_hours:
            violations.append(
                f"fulfilled_late_cp{cp.target_age_hours}_snap_meta_cp_{meta_cp_int}",
            )

    return {
        "video_id": video_id,
        "published_at": video.published_at.isoformat(),
        "checkpoints_now": cp_rows,
        "due_checkpoints_now": [cp.target_age_hours for cp in plan.due_checkpoints],
        "momentum_24h_age_aligned_measurement": (
            None
            if momentum_24 is None
            else {
                "snapshot_id": momentum_24.snapshot_id,
                "age_hours": momentum_24.age_hours,
            }
        ),
        "snapshots": per_snap,
        "fulfilled_late_metadata_violations": violations,
        "interpretation": (
            "fulfilled_late closes only the checkpoint matching target_checkpoint_hours metadata; "
            "momentum 24h requires age-aligned window, not late overdue capture."
        ),
    }


def main() -> int:
    load_dotenv(ROOT / ".env")
    now = utc_now()
    session = SessionLocal()
    try:
        runs = list(
            session.scalars(
                select(MonitoringCycleRun)
                .order_by(MonitoringCycleRun.started_at.desc(), MonitoringCycleRun.id.desc())
                .limit(10),
            ).all(),
        )
        runs_chrono = list(reversed(runs))

        last_cycles = []
        for run in runs_chrono:
            at = run.finished_at or run.started_at
            replay = _diag_cycle_at(session, at)
            last_cycles.append(
                {
                    "run_id": run.run_id,
                    "started_at_utc": run.started_at.isoformat() if run.started_at else None,
                    "finished_at_utc": run.finished_at.isoformat() if run.finished_at else None,
                    "cycle_status": run.cycle_status,
                    "persisted": {
                        "loaded": run.loaded_video_count,
                        "eligible": run.eligible_video_count,
                        "unmonitored": max(0, run.loaded_video_count - run.eligible_video_count),
                        "due": run.due_count,
                        "overdue": run.overdue_count,
                        "selected": run.selected_request_count,
                        "deferred": run.deferred_request_count,
                        "inserted": run.inserted_snapshot_count,
                    },
                    "replay_at_finished_at": replay,
                },
            )

        current = _diag_cycle_at(session, now)
        next_cp = _next_future_checkpoint(session, now)
        funnel = _funnel_24h(session, now)

        fresh_hits = list(
            session.scalars(
                select(KeywordDiscoveryHit)
                .order_by(KeywordDiscoveryHit.discovered_at.desc())
                .limit(10),
            ).all(),
        )
        fresh_videos = [_explain_video_monitoring(session, h.video_id, now) for h in fresh_hits]
        for row, hit in zip(fresh_videos, fresh_hits):
            row["discovered_at_utc"] = hit.discovered_at.isoformat()

        yva = _fulfilled_late_audit(session, "yVaPgwNlfLo", now)
        cohort_tier = _cohort_active_tier_reasons(session, now)
        missing_vph_traces = _missing_vph_samples_from_cohort(session, now, limit=10)

        latest_run = runs[0] if runs else None
        confirmed_root_cause = None
        if latest_run and latest_run.due_count == 0 and latest_run.overdue_count == 0:
            confirmed_root_cause = current.get("inferred_zero_capture_reason")

        report = {
            "generated_at_utc": now.isoformat(),
            "database": "local restore-check (from DATABASE_URL)",
            "constraints": "read_only_no_api_no_writes",
            "last_10_monitoring_cycles": last_cycles,
            "current_pool_diagnosis": current,
            "funnel_last_24h": funnel,
            "next_future_checkpoint": next_cp,
            "no_future_captures_explanation": (
                None
                if next_cp
                else "No pending future checkpoints in active pool (all stopped/expired/completed/fulfilled_late or empty pool)."
            ),
            "fulfilled_late_audit": {
                "yVaPgwNlfLo": yva,
            },
            "fresh_discovery_10": fresh_videos,
            "bootstrap_vph_cohort_735": cohort_tier,
            "missing_vph_traces_10": missing_vph_traces,
            "code_answers": {
                "new_video_without_snapshot_first_capture": (
                    "Yes, if KeywordDiscoveryHit has views_at_discovery and API published_at: "
                    "load_monitored_video_states bootstraps VPH at discovered_at (not now). "
                    "Tier assignment then allows active pool; first capture when checkpoint due/overdue."
                ),
                "without_discovery_hit_or_snapshot": (
                    "No: derive_latest_measurement returns source=unavailable, raw_vph None, "
                    "assign_monitoring_tiers excluded_reason missing_vph — no capture requests."
                ),
                "exploration_without_keyword_discovery_hit": (
                    "TopicExplorationVideoObservation stores no views; no bootstrap path today."
                ),
                "video_views_count_not_used": True,
            },
            "vicious_circle_fix_applied_in_code": (
                "monitoring_video_source._load_discovery_hits_by_video_id wired into load path "
                "(views at discovery time, not views_count/now)."
            ),
            "confirmed_root_cause_zero_capture": confirmed_root_cause,
            "unconfirmed_hypotheses": [
                "Worker dry_run or missing youtube client (would yield inserted=0 despite selected>0)",
                "API budget env override not visible in ORM cycle rows",
            ],
        }
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"artifact": str(OUT_PATH.relative_to(ROOT)), "confirmed_root_cause": confirmed_root_cause}, indent=2))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
