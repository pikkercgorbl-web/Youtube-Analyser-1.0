"""Typed Attention Engine representations (Stage 1.22A). No composite scores."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

ATTENTION_TIMEZONE = "UTC"
YOUTUBE_WATCH_URL_PREFIX = "https://www.youtube.com/watch?v="

AccelerationState = Literal["unavailable", "stable", "accelerating", "decelerating"]
DelayedOutcomeState = Literal["pending", "confirmed", "not_confirmed", "missing", "unavailable"]
ChannelRelativeStatus = Literal["unavailable", "diagnostic", "production_ready"]
PatternKind = Literal["keyword_provenance", "title_phrase", "video_topic"]

REASON_BREAKOUT_HIGH_RANK = "breakout_high_rank"
REASON_HIGH_CURRENT_VPH = "high_current_vph"
REASON_SMALL_CHANNEL_CONTEXT = "small_channel_in_observed_universe"
REASON_CHANNEL_RELATIVE_OUTLIER = "channel_relative_outlier"
REASON_ACCELERATING = "accelerating_velocity"
REASON_CONFIRMED_72H = "confirmed_72h_growth"
REASON_BREAKOUT_ELIGIBLE = "breakout_eligible"

REASON_MULTI_VIDEO = "multi_video_evidence"
REASON_CHANNEL_DIVERSITY = "channel_diversity"
REASON_BREAKOUT_MEMBERS = "breakout_member_videos"
REASON_RECENT_ACTIVITY = "recent_window_activity"
REASON_KEYWORD_PROVENANCE = "shared_keyword_provenance"
REASON_TITLE_PHRASE = "shared_title_phrase"
REASON_VIDEO_TOPIC = "shared_video_topic"

FAMILY_REASON_TOKEN_OVERLAP = "high_token_overlap"
FAMILY_REASON_SHARED_VIDEOS = "shared_video_membership"
FAMILY_REASON_SHARED_CHANNELS = "shared_channel_membership"
FAMILY_REASON_SHARED_KEYWORDS = "shared_keyword_context"
FAMILY_REASON_SINGLE_MEMBER = "single_member_family"

FLAG_REPEATED_TITLE_TEMPLATE = "repeated_title_template"
FLAG_BROAD_KEYWORD_GROUP = "broad_keyword_group"
FLAG_KEYWORD_ONLY = "keyword_only"
FLAG_CROSS_SOURCE = "cross_source_supported"
FLAG_PHRASE_SUPPORTED = "phrase_supported"
FLAG_TOPIC_SUPPORTED = "topic_supported"

REASON_MULTI_BREAKOUT = "multiple_recent_breakouts"
REASON_VPH_ABOVE_PREVIOUS = "recent_median_vph_above_previous"
REASON_REPEATED_AGE_ALIGNED_IMPROVEMENT = "repeated_age_aligned_improvement"
REASON_CONFIRMED_72H_CLUSTER = "confirmed_72h_cluster"
REASON_SUBSCRIBER_GROWTH = "subscriber_growth"
REASON_CONTENT_MOMENTUM = "content_momentum"
REASON_CONTEXT_BREAKOUT_ELIGIBLE = "context_breakout_eligible"
REASON_CONTEXT_KEYWORD_72H_GROWTH = "context_keyword_72h_view_growth"
REASON_CONTEXT_SUBSCRIBER_GROWTH = "context_subscriber_growth"


def youtube_watch_url(video_id: str) -> str:
    return f"{YOUTUBE_WATCH_URL_PREFIX}{video_id.strip()}"


@dataclass(frozen=True, slots=True)
class ChannelRelativeSignal:
    status: ChannelRelativeStatus
    baseline_quality: str
    comparable_video_count: int
    vph_vs_channel_median: float | None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VideoWinner:
    video_id: str
    title: str
    channel_id: str
    channel_title: str
    youtube_url: str
    published_at: datetime | None
    age_hours: float | None
    views: int | None
    vph: float | None
    subscribers: int | None
    breakout_rank: int | None
    breakout_eligible: bool
    channel_relative_signal: ChannelRelativeSignal | None
    acceleration_state: AccelerationState
    delayed_outcome_state: DelayedOutcomeState
    delayed_outcome_growth: int | None
    reason_codes: tuple[str, ...]
    human_reasons: tuple[str, ...]
    keyword_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class PatternCandidate:
    pattern_key: str
    kind: PatternKind
    label: str
    video_count: int
    channel_count: int
    keyword_count: int
    breakout_video_count: int
    small_channel_winner_count: int
    first_seen_at: datetime | None
    latest_seen_at: datetime | None
    videos_last_24h: int
    videos_previous_24h: int
    videos_previous_48_24h: int
    participating_video_ids: tuple[str, ...]
    participating_channel_ids: tuple[str, ...]
    participating_keyword_ids: tuple[int, ...]
    reason_codes: tuple[str, ...]
    human_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChannelMomentum:
    channel_id: str
    channel_title: str
    subscriber_count_latest: int | None
    observed_video_count: int
    recent_video_count: int
    previous_video_count: int
    breakout_video_count: int
    confirmed_72h_count: int
    recent_median_vph: float | None
    previous_median_vph: float | None
    recent_median_vph_vs_previous: float | None
    subscriber_growth_absolute: int | None
    subscriber_growth_pct: float | None
    subscriber_growth_available: bool
    first_observed_at: datetime | None
    latest_observed_at: datetime | None
    representative_video_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    human_reasons: tuple[str, ...]
    recent_window_days: int
    previous_window_days: int
    momentum_horizon_hours: int = 24
    momentum_horizon_tolerance_hours: float = 6.0
    recent_eligible_count: int = 0
    previous_eligible_count: int = 0
    recent_measurable_count: int = 0
    previous_measurable_count: int = 0
    recent_improvement_count: int = 0
    improvement_ratio_threshold: float = 1.5
    previous_baseline_zero: bool = False
    incompleteness_notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AttentionEngineConfig:
    window_hours: int = 24
    video_limit: int = 50
    pattern_limit: int = 20
    channel_limit: int = 20
    timezone_name: str = ATTENTION_TIMEZONE
    channel_recent_days: int = 7
    channel_previous_days: int = 7
    channel_momentum_horizon_hours: int = 24
    channel_momentum_horizon_tolerance_hours: float = 6.0
    channel_momentum_improvement_ratio: float = 1.5
    min_acceleration_snapshots: int = 3
    min_pattern_videos: int = 2
    min_pattern_channels: int = 2
    max_keyword_pattern_videos: int = 30
    breakout_high_rank_max: int = 20
    channel_baseline_max_channel_videos: int = 200


@dataclass(frozen=True, slots=True)
class AttentionSummary:
    run_id: str | None
    computed_at: datetime
    timezone_name: str
    window_hours: int
    window_start: datetime
    window_end: datetime
    source: str
    candidate_video_count: int
    winner_count: int
    pattern_count: int
    channel_momentum_count: int
    video_limit: int
    pattern_limit: int
    channel_limit: int
    notes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PatternFamily:
    family_key: str
    label: str
    family_kind: PatternKind
    member_pattern_keys: tuple[str, ...]
    member_labels: tuple[str, ...]
    video_ids: tuple[str, ...]
    channel_ids: tuple[str, ...]
    keyword_ids: tuple[int, ...]
    video_count: int
    channel_count: int
    keyword_count: int
    breakout_eligible_count: int
    videos_last_24h: int
    videos_previous_24h: int
    videos_previous_48_24h: int
    grouping_reasons: tuple[str, ...]
    quality_flags: tuple[str, ...]
    support_sources: tuple[str, ...]
    first_seen_at: datetime | None
    latest_seen_at: datetime | None


@dataclass(frozen=True, slots=True)
class AttentionEngineResult:
    summary: AttentionSummary
    video_winners: tuple[VideoWinner, ...]
    patterns: tuple[PatternCandidate, ...]
    channels: tuple[ChannelMomentum, ...]
    families: tuple[PatternFamily, ...] = ()


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def video_winner_to_dict(row: VideoWinner) -> dict[str, Any]:
    payload = asdict(row)
    payload["published_at"] = _dt(row.published_at)
    if row.channel_relative_signal is not None:
        payload["channel_relative_signal"] = asdict(row.channel_relative_signal)
        payload["channel_relative_signal"]["notes"] = list(row.channel_relative_signal.notes)
    payload["reason_codes"] = list(row.reason_codes)
    payload["human_reasons"] = list(row.human_reasons)
    payload["keyword_ids"] = list(row.keyword_ids)
    return payload


def pattern_to_dict(row: PatternCandidate) -> dict[str, Any]:
    payload = asdict(row)
    payload["first_seen_at"] = _dt(row.first_seen_at)
    payload["latest_seen_at"] = _dt(row.latest_seen_at)
    for key in (
        "participating_video_ids",
        "participating_channel_ids",
        "participating_keyword_ids",
        "reason_codes",
        "human_reasons",
    ):
        payload[key] = list(payload[key])
    return payload


def channel_momentum_to_dict(row: ChannelMomentum) -> dict[str, Any]:
    payload = asdict(row)
    payload["first_observed_at"] = _dt(row.first_observed_at)
    payload["latest_observed_at"] = _dt(row.latest_observed_at)
    payload["representative_video_ids"] = list(row.representative_video_ids)
    payload["reason_codes"] = list(row.reason_codes)
    payload["human_reasons"] = list(row.human_reasons)
    payload["incompleteness_notes"] = list(row.incompleteness_notes)
    return payload


def pattern_family_to_dict(row: PatternFamily) -> dict[str, Any]:
    payload = asdict(row)
    payload["first_seen_at"] = _dt(row.first_seen_at)
    payload["latest_seen_at"] = _dt(row.latest_seen_at)
    for key in (
        "member_pattern_keys",
        "member_labels",
        "video_ids",
        "channel_ids",
        "keyword_ids",
        "grouping_reasons",
        "quality_flags",
        "support_sources",
    ):
        payload[key] = list(payload[key])
    return payload


def attention_result_to_dict(result: AttentionEngineResult) -> dict[str, Any]:
    summary = asdict(result.summary)
    summary["computed_at"] = _dt(result.summary.computed_at)
    summary["window_start"] = _dt(result.summary.window_start)
    summary["window_end"] = _dt(result.summary.window_end)
    return {
        "summary": summary,
        "video_winners": [video_winner_to_dict(row) for row in result.video_winners],
        "patterns": [pattern_to_dict(row) for row in result.patterns],
        "channels": [channel_momentum_to_dict(row) for row in result.channels],
        "families": [pattern_family_to_dict(row) for row in result.families],
    }
