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

# Stage 1.23C.1A — DI winner priority (OFF by default; total budget unchanged).
ENV_OUTCOME_CAPTURE_DI_WINNER_PRIORITY = "OUTCOME_CAPTURE_DI_WINNER_PRIORITY"
DEFAULT_OUTCOME_CAPTURE_DI_WINNER_PRIORITY_ENABLED = False
DEFAULT_OUTCOME_CAPTURE_PRIORITY_MAX_SLOTS = 30
DEFAULT_OUTCOME_CAPTURE_BACKGROUND_MIN_SLOTS = 70

def parse_outcome_capture_di_winner_priority_value(value: object) -> bool:
    """Re-export for tests; implementation lives in app.core.env_parsing."""
    from app.core.env_parsing import parse_outcome_capture_di_winner_priority_value as _parse

    return _parse(value)


def _load_outcome_capture_settings():
    from app.core.config import Settings

    return Settings()


@dataclass(frozen=True, slots=True)
class OutcomeCaptureBudgetPolicy:
    max_videos_per_cycle: int = DEFAULT_OUTCOME_CAPTURE_MAX_VIDEOS_PER_CYCLE
    batch_size: int = DEFAULT_OUTCOME_CAPTURE_BATCH_SIZE
    di_winner_priority_enabled: bool = DEFAULT_OUTCOME_CAPTURE_DI_WINNER_PRIORITY_ENABLED
    priority_max_slots: int = DEFAULT_OUTCOME_CAPTURE_PRIORITY_MAX_SLOTS
    background_min_slots: int = DEFAULT_OUTCOME_CAPTURE_BACKGROUND_MIN_SLOTS


def outcome_capture_budget_from_env() -> OutcomeCaptureBudgetPolicy:
    """Resolve budget via Settings (.env + defaults); process env overrides .env file."""
    settings = _load_outcome_capture_settings()
    return OutcomeCaptureBudgetPolicy(
        di_winner_priority_enabled=settings.outcome_capture_di_winner_priority_enabled,
    )


def outcome_capture_budget_for_cycle(
    *,
    max_videos_per_cycle: int | None = None,
) -> OutcomeCaptureBudgetPolicy:
    """Env DI priority + defaults; optional worker/CLI override for cycle video cap."""
    base = outcome_capture_budget_from_env()
    if max_videos_per_cycle is None:
        return base
    return OutcomeCaptureBudgetPolicy(
        max_videos_per_cycle=max_videos_per_cycle,
        batch_size=base.batch_size,
        di_winner_priority_enabled=base.di_winner_priority_enabled,
        priority_max_slots=base.priority_max_slots,
        background_min_slots=base.background_min_slots,
    )
