"""Configuration for delayed outcome capture (Stage 1.20E.2)."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.keyword_performance_evaluation import HORIZON_HOURS

OUTCOME_CAPTURE_SOURCE = "keyword_outcome_worker"
OUTCOME_CHECKPOINT_AGE_HOURS = HORIZON_HOURS

# One hour: ±12h tolerance allows many in-window attempts without 15m churn.
DEFAULT_OUTCOME_CAPTURE_INTERVAL_SECONDS = 3600
DEFAULT_OUTCOME_CAPTURE_ERROR_BACKOFF_SECONDS = 300
DEFAULT_OUTCOME_CAPTURE_MAX_VIDEOS_PER_CYCLE = 100
DEFAULT_OUTCOME_CAPTURE_BATCH_SIZE = 50


@dataclass(frozen=True, slots=True)
class OutcomeCaptureBudgetPolicy:
    max_videos_per_cycle: int = DEFAULT_OUTCOME_CAPTURE_MAX_VIDEOS_PER_CYCLE
    batch_size: int = DEFAULT_OUTCOME_CAPTURE_BATCH_SIZE
