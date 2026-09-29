"""Breakout ranking v1 — cap-independent analyst attention ordering (Stage 1.17B)."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.monitoring_tier_budget_policy import MonitoringTierPolicy
from app.services.monitoring_video_source import MonitoredVideoState

BREAKOUT_RANK_VERSION = "breakout_v1"
BREAKOUT_RANKING_SIGNAL = "vph"
BREAKOUT_RANKING_REASON = "sorted_by_vph_desc_views_tiebreak_video_id"


@dataclass(frozen=True, slots=True)
class BreakoutRankedVideo:
    video_id: str
    rank: int
    ranking_value: float
    ranking_views: int
    breakout_rank_version: str = BREAKOUT_RANK_VERSION
    breakout_ranking_signal: str = BREAKOUT_RANKING_SIGNAL
    breakout_ranking_reason: str = BREAKOUT_RANKING_REASON


def breakout_fundamental_eligibility(
    state: MonitoredVideoState,
    *,
    max_age_monitoring_hours: float,
) -> tuple[bool, str | None]:
    """
    Fundamental breakout eligibility (independent of tier, caps, planner).

    Returns (eligible, excluded_reason).
    """
    if state.is_short or state.content_format == "short":
        return False, "short_format"
    if state.is_live or state.content_format == "live":
        return False, "live_format"
    if state.content_format not in (None, "regular"):
        return False, "non_regular_format"
    if state.age_hours is None:
        return False, "missing_age_hours"
    if state.age_hours > max_age_monitoring_hours:
        return False, "stale_discovery_age"
    if state.raw_vph is None:
        return False, "missing_vph"
    return True, None


def _breakout_sort_key(state: MonitoredVideoState, *, views: int) -> tuple:
    return (-float(state.raw_vph), -views, state.video_id)


def rank_breakout_v1(
    states: list[MonitoredVideoState],
    *,
    views_by_video_id: dict[str, int | None] | None = None,
    tier_policy: MonitoringTierPolicy | None = None,
) -> list[BreakoutRankedVideo]:
    """
    Deterministic breakout order: VPH DESC, views DESC, video_id ASC.

    Only fundamentally eligible states are ranked. No DB access.
    """
    cfg = tier_policy or MonitoringTierPolicy()
    max_age = cfg.max_age_monitoring_hours
    views_map = views_by_video_id or {}

    eligible: list[MonitoredVideoState] = []
    for state in states:
        ok, _ = breakout_fundamental_eligibility(state, max_age_monitoring_hours=max_age)
        if ok:
            eligible.append(state)

    def views_for(state: MonitoredVideoState) -> int:
        raw = views_map.get(state.video_id)
        if raw is not None:
            return int(raw)
        return 0

    ordered = sorted(eligible, key=lambda s: _breakout_sort_key(s, views=views_for(s)))

    ranked: list[BreakoutRankedVideo] = []
    for index, state in enumerate(ordered, start=1):
        ranked.append(
            BreakoutRankedVideo(
                video_id=state.video_id,
                rank=index,
                ranking_value=float(state.raw_vph),  # type: ignore[arg-type]
                ranking_views=views_for(state),
            ),
        )
    return ranked
