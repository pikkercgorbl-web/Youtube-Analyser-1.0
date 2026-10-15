"""Read-model helpers for monitoring cycle UI (Fix 3B)."""

from __future__ import annotations

from typing import Literal, Protocol

PartialPrimaryCause = Literal["none", "missing_only", "execution_errors", "mixed"]


class MonitoringCycleCounts(Protocol):
    cycle_status: str
    missing_count: int
    fetch_failed_count: int
    validation_failed_count: int
    persistence_failed_count: int


def monitoring_execution_error_count(cycle: MonitoringCycleCounts) -> int:
    return (
        int(cycle.fetch_failed_count)
        + int(cycle.validation_failed_count)
        + int(cycle.persistence_failed_count)
    )


def monitoring_partial_primary_cause(cycle: MonitoringCycleCounts) -> PartialPrimaryCause:
    if str(cycle.cycle_status).lower() != "partial":
        return "none"
    missing = int(cycle.missing_count)
    errors = monitoring_execution_error_count(cycle)
    if missing > 0 and errors == 0:
        return "missing_only"
    if missing == 0 and errors > 0:
        return "execution_errors"
    if missing > 0 and errors > 0:
        return "mixed"
    return "none"


def monitoring_cycle_status_detail(cycle: MonitoringCycleCounts) -> str | None:
    """Short Russian explanation for partial cycles; None if not needed."""
    cause = monitoring_partial_primary_cause(cycle)
    missing = int(cycle.missing_count)
    errors = monitoring_execution_error_count(cycle)
    if cause == "missing_only":
        return (
            f"Частично: {missing} запрос(ов) — видео не вернулось в ответе YouTube API "
            f"(missing), остальные снимки сохранены."
        )
    if cause == "execution_errors":
        return f"Частично: ошибки захвата (fetch/validation/persist): {errors}."
    if cause == "mixed":
        return (
            f"Частично: missing={missing}, ошибки захвата={errors}."
        )
    if str(cycle.cycle_status).lower() == "partial":
        return "Частично: причина не отражена в сохранённых счётчиках (см. логи цикла)."
    return None
