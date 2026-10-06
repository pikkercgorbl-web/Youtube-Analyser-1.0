"""Delayed keyword outcome capture types (Stage 1.20E.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

OutcomeCaptureState = Literal[
    "pending",
    "capture_due",
    "capture_overdue",
    "satisfied",
    "expired",
]

OutcomeAttributionMode = Literal["all_hits", "first_discovery"]


@dataclass(frozen=True, slots=True)
class OutcomeObservationRecord:
    keyword_id: int
    video_id: str
    channel_id: str | None
    discovered_at: datetime
    views_at_discovery: int | None


@dataclass(frozen=True, slots=True)
class OutcomeObservationPlan:
    keyword_id: int
    video_id: str
    discovered_at: datetime
    target_at: datetime
    window_start: datetime
    window_end: datetime
    state: OutcomeCaptureState
    hours_until_window_end: float | None


@dataclass(frozen=True, slots=True)
class OutcomeVideoFetchCandidate:
    video_id: str
    channel_id: str | None
    priority_hours_to_window_end: float
    observation_count: int
    states: tuple[OutcomeCaptureState, ...]


@dataclass
class DelayedOutcomeCapturePlan:
    attribution_mode: OutcomeAttributionMode
    reference_at: datetime
    attributed_observation_count: int = 0
    pending_count: int = 0
    capture_due_count: int = 0
    capture_overdue_count: int = 0
    satisfied_count: int = 0
    expired_count: int = 0
    unique_due_video_count: int = 0
    observations: list[OutcomeObservationPlan] = field(default_factory=list)
    fetch_candidates: list[OutcomeVideoFetchCandidate] = field(default_factory=list)
