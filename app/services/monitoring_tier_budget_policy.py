"""Monitoring tier and API budget policy (Stage 1.13A — planning only)."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.services.radar_candidate_analysis import _percentile
from app.services.snapshot_collection_policy import (
    SnapshotCaptureRequest,
    SnapshotCollectionPolicy,
)

DEFAULT_TIER_A_TOP_FRACTION = 0.15
DEFAULT_TIER_B_NEXT_FRACTION = 0.35
DEFAULT_TIER_A_MAX_AGE_HOURS = 24.0
DEFAULT_TIER_AB_MAX_AGE_HOURS = 48.0
DEFAULT_MAX_AGE_MONITORING_HOURS = 72.0
DEFAULT_VPH_VS_MEDIAN_PROMOTION = 3.0
DEFAULT_MAX_ACTIVE_VIDEOS_PER_CHANNEL = 3
DEFAULT_MAX_ACTIVE_MONITORED_VIDEOS = 2000
DEFAULT_MAX_CAPTURE_REQUESTS_PER_CYCLE = 500
DEFAULT_TIER_C_FAIR_SHARE_FRACTION = 0.12

TIER_A_CHECKPOINTS: tuple[int, ...] = (6, 12, 24, 48, 72)
TIER_B_CHECKPOINTS: tuple[int, ...] = (12, 24, 48, 72)
TIER_C_CHECKPOINTS: tuple[int, ...] = (24, 72)


class MonitoringTier(str, enum.Enum):
    A = "A"
    B = "B"
    C = "C"
    UNMONITORED = "UNMONITORED"


@dataclass(frozen=True, slots=True)
class MonitoringTierPolicy:
    tier_a_top_fraction: float = DEFAULT_TIER_A_TOP_FRACTION
    tier_b_next_fraction: float = DEFAULT_TIER_B_NEXT_FRACTION
    tier_a_max_age_hours: float = DEFAULT_TIER_A_MAX_AGE_HOURS
    tier_ab_max_age_hours: float = DEFAULT_TIER_AB_MAX_AGE_HOURS
    max_age_monitoring_hours: float = DEFAULT_MAX_AGE_MONITORING_HOURS
    allow_tier_a_after_24h: bool = False
    vph_vs_median_promotion_multiplier: float = DEFAULT_VPH_VS_MEDIAN_PROMOTION
    max_active_videos_per_channel: int = DEFAULT_MAX_ACTIVE_VIDEOS_PER_CHANNEL
    tier_a_checkpoints: tuple[int, ...] = TIER_A_CHECKPOINTS
    tier_b_checkpoints: tuple[int, ...] = TIER_B_CHECKPOINTS
    tier_c_checkpoints: tuple[int, ...] = TIER_C_CHECKPOINTS


@dataclass(frozen=True, slots=True)
class ApiBudgetPolicy:
    max_active_monitored_videos: int = DEFAULT_MAX_ACTIVE_MONITORED_VIDEOS
    max_capture_requests_per_cycle: int = DEFAULT_MAX_CAPTURE_REQUESTS_PER_CYCLE
    tier_c_fair_share_fraction: float = DEFAULT_TIER_C_FAIR_SHARE_FRACTION


@dataclass(frozen=True, slots=True)
class TierCandidateInput:
    """Decision-time inputs only (no future outcome fields)."""

    video_id: str
    channel_id: str
    raw_vph: float | None
    age_hours: float | None
    published_at_present: bool = True
    content_format: str | None = "regular"
    is_short: bool | None = False
    is_live: bool | None = False
    channel_velocity_baseline_status: str | None = None
    vph_vs_channel_median: float | None = None


@dataclass(frozen=True, slots=True)
class MonitoringDecision:
    video_id: str
    channel_id: str
    tier: MonitoringTier
    reason_codes: tuple[str, ...]
    raw_vph: float | None
    age_hours: float | None
    baseline_status: str | None
    vph_vs_channel_median: float | None
    checkpoint_hours: tuple[int, ...]
    eligible: bool
    excluded_reason: str | None = None
    priority_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChannelCapResult:
    retained: tuple[MonitoringDecision, ...]
    excluded: tuple[MonitoringDecision, ...]


@dataclass(frozen=True, slots=True)
class BudgetAllocationResult:
    total_candidates: int
    monitored_count: int
    excluded_count: int
    tier_counts: dict[str, int]
    channel_cap_excluded_count: int
    requested_count: int
    selected_for_capture_count: int
    deferred_count: int
    fairness_reserved_count: int
    selected_requests: tuple[SnapshotCaptureRequest, ...] = ()
    deferred_requests: tuple[SnapshotCaptureRequest, ...] = ()


@dataclass(frozen=True, slots=True)
class CaptureRequestBudgetContext:
    request: SnapshotCaptureRequest
    tier: MonitoringTier
    raw_vph: float | None
    is_overdue: bool
    time_to_checkpoint_expiry_hours: float | None


def checkpoint_hours_for_tier(tier: MonitoringTier, policy: MonitoringTierPolicy) -> tuple[int, ...]:
    if tier == MonitoringTier.A:
        return policy.tier_a_checkpoints
    if tier == MonitoringTier.B:
        return policy.tier_b_checkpoints
    if tier == MonitoringTier.C:
        return policy.tier_c_checkpoints
    return ()


def snapshot_collection_policy_for_tier(
    tier: MonitoringTier,
    policy: MonitoringTierPolicy,
) -> SnapshotCollectionPolicy:
    return SnapshotCollectionPolicy(checkpoint_hours=checkpoint_hours_for_tier(tier, policy))


def _is_format_unmonitored(item: TierCandidateInput) -> str | None:
    if item.is_short is True or item.content_format == "short":
        return "short_format"
    if item.is_live is True or item.content_format == "live":
        return "live_format"
    if not item.published_at_present:
        return "missing_published_at"
    if item.content_format not in (None, "regular"):
        return "non_regular_format"
    return None


def _vph_band_tier(
    vph: float,
    *,
    p50: float,
    p85: float,
) -> MonitoringTier:
    if vph >= p85:
        return MonitoringTier.A
    if vph >= p50:
        return MonitoringTier.B
    return MonitoringTier.C


def _apply_age_caps(
    tier: MonitoringTier,
    age_hours: float | None,
    policy: MonitoringTierPolicy,
) -> tuple[MonitoringTier, tuple[str, ...]]:
    reasons: list[str] = []
    if age_hours is None:
        return MonitoringTier.UNMONITORED, ("missing_age_hours",)

    if age_hours > policy.max_age_monitoring_hours:
        return MonitoringTier.UNMONITORED, ("stale_discovery_age",)

    if age_hours > policy.tier_ab_max_age_hours:
        if tier in (MonitoringTier.A, MonitoringTier.B):
            tier = MonitoringTier.C
            reasons.append("age_demoted_to_c")
        return tier, tuple(reasons)

    if age_hours > policy.tier_a_max_age_hours and tier == MonitoringTier.A:
        if policy.allow_tier_a_after_24h:
            return tier, tuple(reasons)
        tier = MonitoringTier.B
        reasons.append("age_demoted_a_to_b")
    return tier, tuple(reasons)


def _apply_velocity_promotion(
    tier: MonitoringTier,
    item: TierCandidateInput,
    policy: MonitoringTierPolicy,
    age_hours: float | None,
) -> tuple[MonitoringTier, tuple[str, ...]]:
    reasons: list[str] = []
    status = item.channel_velocity_baseline_status
    if status not in ("ok", "partial"):
        return tier, tuple(reasons)
    if item.vph_vs_channel_median is None:
        return tier, tuple(reasons)
    if item.vph_vs_channel_median < policy.vph_vs_median_promotion_multiplier:
        return tier, tuple(reasons)
    if age_hours is not None and age_hours > policy.tier_a_max_age_hours:
        return tier, tuple(reasons)

    if tier == MonitoringTier.C:
        tier = MonitoringTier.B
        reasons.append("velocity_promotion_c_to_b")
    elif tier == MonitoringTier.B:
        tier = MonitoringTier.A
        reasons.append("velocity_promotion_b_to_a")
    return tier, tuple(reasons)


def compute_vph_percentile_thresholds(
    vph_values: Sequence[float],
    policy: MonitoringTierPolicy,
) -> tuple[float | None, float | None]:
    if not vph_values:
        return None, None
    sorted_values = sorted(float(v) for v in vph_values)
    top_cut = 100.0 * (1.0 - policy.tier_a_top_fraction)
    b_cut = 100.0 * (1.0 - policy.tier_a_top_fraction - policy.tier_b_next_fraction)
    p85 = _percentile(sorted_values, top_cut)
    p50 = _percentile(sorted_values, b_cut)
    return p50, p85


def assign_monitoring_tiers(
    candidates: Sequence[TierCandidateInput],
    policy: MonitoringTierPolicy | None = None,
) -> list[MonitoringDecision]:
    cfg = policy or MonitoringTierPolicy()
    ordered = sorted(candidates, key=lambda row: row.video_id)

    percentile_pool = [
        float(item.raw_vph)
        for item in ordered
        if _is_format_unmonitored(item) is None and item.raw_vph is not None
    ]
    p50, p85 = compute_vph_percentile_thresholds(percentile_pool, cfg)

    decisions: list[MonitoringDecision] = []
    for item in ordered:
        reasons: list[str] = []
        fmt_reason = _is_format_unmonitored(item)
        if fmt_reason is not None:
            decisions.append(
                MonitoringDecision(
                    video_id=item.video_id,
                    channel_id=item.channel_id,
                    tier=MonitoringTier.UNMONITORED,
                    reason_codes=(fmt_reason,),
                    raw_vph=item.raw_vph,
                    age_hours=item.age_hours,
                    baseline_status=item.channel_velocity_baseline_status,
                    vph_vs_channel_median=item.vph_vs_channel_median,
                    checkpoint_hours=(),
                    eligible=False,
                    excluded_reason=fmt_reason,
                ),
            )
            continue

        if item.raw_vph is None:
            decisions.append(
                MonitoringDecision(
                    video_id=item.video_id,
                    channel_id=item.channel_id,
                    tier=MonitoringTier.UNMONITORED,
                    reason_codes=("missing_vph",),
                    raw_vph=None,
                    age_hours=item.age_hours,
                    baseline_status=item.channel_velocity_baseline_status,
                    vph_vs_channel_median=item.vph_vs_channel_median,
                    checkpoint_hours=(),
                    eligible=False,
                    excluded_reason="missing_vph",
                ),
            )
            continue

        assert p50 is not None and p85 is not None
        tier = _vph_band_tier(float(item.raw_vph), p50=p50, p85=p85)
        reasons.append("vph_percentile_band")

        tier, age_reasons = _apply_age_caps(tier, item.age_hours, cfg)
        reasons.extend(age_reasons)

        if tier == MonitoringTier.UNMONITORED:
            decisions.append(
                MonitoringDecision(
                    video_id=item.video_id,
                    channel_id=item.channel_id,
                    tier=tier,
                    reason_codes=tuple(reasons),
                    raw_vph=item.raw_vph,
                    age_hours=item.age_hours,
                    baseline_status=item.channel_velocity_baseline_status,
                    vph_vs_channel_median=item.vph_vs_channel_median,
                    checkpoint_hours=(),
                    eligible=False,
                    excluded_reason=reasons[-1] if reasons else "unmonitored",
                ),
            )
            continue

        tier, promo_reasons = _apply_velocity_promotion(tier, item, cfg, item.age_hours)
        reasons.extend(promo_reasons)
        tier, age_reasons2 = _apply_age_caps(tier, item.age_hours, cfg)
        reasons.extend(age_reasons2)

        if tier == MonitoringTier.UNMONITORED:
            decisions.append(
                MonitoringDecision(
                    video_id=item.video_id,
                    channel_id=item.channel_id,
                    tier=tier,
                    reason_codes=tuple(reasons),
                    raw_vph=item.raw_vph,
                    age_hours=item.age_hours,
                    baseline_status=item.channel_velocity_baseline_status,
                    vph_vs_channel_median=item.vph_vs_channel_median,
                    checkpoint_hours=(),
                    eligible=False,
                    excluded_reason=reasons[-1],
                ),
            )
            continue

        checkpoints = checkpoint_hours_for_tier(tier, cfg)
        decisions.append(
            MonitoringDecision(
                video_id=item.video_id,
                channel_id=item.channel_id,
                tier=tier,
                reason_codes=tuple(reasons),
                raw_vph=item.raw_vph,
                age_hours=item.age_hours,
                baseline_status=item.channel_velocity_baseline_status,
                vph_vs_channel_median=item.vph_vs_channel_median,
                checkpoint_hours=checkpoints,
                eligible=True,
                priority_metadata={
                    "p50_vph_threshold": p50,
                    "p85_vph_threshold": p85,
                },
            ),
        )

    return decisions


def _decision_sort_key(decision: MonitoringDecision) -> tuple:
    tier_rank = {
        MonitoringTier.A: 0,
        MonitoringTier.B: 1,
        MonitoringTier.C: 2,
        MonitoringTier.UNMONITORED: 99,
    }[decision.tier]
    age = decision.age_hours if decision.age_hours is not None else 999999.0
    vph = decision.raw_vph if decision.raw_vph is not None else -1.0
    return (tier_rank, age, -vph, decision.video_id)


def apply_channel_active_cap(
    decisions: Sequence[MonitoringDecision],
    max_per_channel: int,
) -> ChannelCapResult:
    eligible = [d for d in decisions if d.eligible and d.tier != MonitoringTier.UNMONITORED]
    ineligible = [d for d in decisions if not d.eligible or d.tier == MonitoringTier.UNMONITORED]

    by_channel: dict[str, list[MonitoringDecision]] = {}
    for decision in eligible:
        by_channel.setdefault(decision.channel_id, []).append(decision)

    retained: list[MonitoringDecision] = []
    excluded: list[MonitoringDecision] = []
    for channel_id in sorted(by_channel.keys()):
        rows = sorted(by_channel[channel_id], key=_decision_sort_key)
        keep = rows[: max(0, max_per_channel)]
        drop = rows[max(0, max_per_channel) :]
        retained.extend(keep)
        for decision in drop:
            excluded.append(
                MonitoringDecision(
                    video_id=decision.video_id,
                    channel_id=decision.channel_id,
                    tier=decision.tier,
                    reason_codes=decision.reason_codes + ("channel_active_cap",),
                    raw_vph=decision.raw_vph,
                    age_hours=decision.age_hours,
                    baseline_status=decision.baseline_status,
                    vph_vs_channel_median=decision.vph_vs_channel_median,
                    checkpoint_hours=decision.checkpoint_hours,
                    eligible=False,
                    excluded_reason="channel_active_cap",
                    priority_metadata=dict(decision.priority_metadata),
                ),
            )

    retained_sorted = sorted(retained, key=lambda row: row.video_id)
    excluded_sorted = sorted(excluded + ineligible, key=lambda row: row.video_id)
    return ChannelCapResult(retained=tuple(retained_sorted), excluded=tuple(excluded_sorted))


def apply_global_monitoring_cap(
    decisions: Sequence[MonitoringDecision],
    max_active: int,
) -> ChannelCapResult:
    eligible = sorted(
        [d for d in decisions if d.eligible],
        key=_decision_sort_key,
    )
    retained = eligible[: max(0, max_active)]
    excluded = eligible[max(0, max_active) :]
    excluded_rows = [
        MonitoringDecision(
            video_id=row.video_id,
            channel_id=row.channel_id,
            tier=row.tier,
            reason_codes=row.reason_codes + ("global_monitoring_cap",),
            raw_vph=row.raw_vph,
            age_hours=row.age_hours,
            baseline_status=row.baseline_status,
            vph_vs_channel_median=row.vph_vs_channel_median,
            checkpoint_hours=row.checkpoint_hours,
            eligible=False,
            excluded_reason="global_monitoring_cap",
            priority_metadata=dict(row.priority_metadata),
        )
        for row in excluded
    ]
    ineligible = [d for d in decisions if not d.eligible]
    return ChannelCapResult(
        retained=tuple(retained),
        excluded=tuple(sorted(excluded_rows + ineligible, key=lambda r: r.video_id)),
    )


def _capture_budget_sort_key(ctx: CaptureRequestBudgetContext) -> tuple:
    tier_rank = {
        MonitoringTier.A: 0,
        MonitoringTier.B: 1,
        MonitoringTier.C: 2,
        MonitoringTier.UNMONITORED: 99,
    }[ctx.tier]
    overdue_rank = 0 if ctx.is_overdue else 1
    expiry = ctx.time_to_checkpoint_expiry_hours
    expiry_key = expiry if expiry is not None else 999999.0
    vph = ctx.raw_vph if ctx.raw_vph is not None else -1.0
    return (
        overdue_rank,
        expiry_key,
        tier_rank,
        ctx.request.checkpoint_age_hours,
        -vph,
        ctx.request.video_id,
    )


def allocate_capture_budget(
    contexts: Sequence[CaptureRequestBudgetContext],
    budget_policy: ApiBudgetPolicy | None = None,
) -> BudgetAllocationResult:
    cfg = budget_policy or ApiBudgetPolicy()
    ordered = sorted(contexts, key=_capture_budget_sort_key)
    max_requests = max(0, cfg.max_capture_requests_per_cycle)

    tier_c = [ctx for ctx in ordered if ctx.tier == MonitoringTier.C]
    c_quota = min(len(tier_c), max(0, int(round(max_requests * cfg.tier_c_fair_share_fraction))))

    selected: list[CaptureRequestBudgetContext] = []
    selected_ids: set[tuple[str, int]] = set()

    for ctx in tier_c[:c_quota]:
        key = (ctx.request.video_id, ctx.request.checkpoint_age_hours)
        if key not in selected_ids:
            selected.append(ctx)
            selected_ids.add(key)

    for ctx in ordered:
        if len(selected) >= max_requests:
            break
        key = (ctx.request.video_id, ctx.request.checkpoint_age_hours)
        if key in selected_ids:
            continue
        selected.append(ctx)
        selected_ids.add(key)

    selected_set = {id(ctx) for ctx in selected}
    deferred = [ctx for ctx in ordered if id(ctx) not in selected_set]

    tier_counts: dict[str, int] = {}
    for ctx in selected:
        tier_counts[ctx.tier.value] = tier_counts.get(ctx.tier.value, 0) + 1

    return BudgetAllocationResult(
        total_candidates=len(contexts),
        monitored_count=len({ctx.request.video_id for ctx in contexts}),
        excluded_count=0,
        tier_counts=tier_counts,
        channel_cap_excluded_count=0,
        requested_count=len(contexts),
        selected_for_capture_count=len(selected),
        deferred_count=len(deferred),
        fairness_reserved_count=min(c_quota, len(selected)),
        selected_requests=tuple(ctx.request for ctx in selected),
        deferred_requests=tuple(ctx.request for ctx in deferred),
    )
