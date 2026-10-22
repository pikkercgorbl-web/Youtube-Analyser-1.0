"""Fix 3B — monitoring partial presentation helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.monitoring_cycle_presentation import (
    monitoring_execution_error_count,
    monitoring_partial_primary_cause,
    monitoring_cycle_status_detail,
)


class _Row:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_missing_only_partial() -> None:
    row = _Row(
        cycle_status="partial",
        missing_count=1,
        fetch_failed_count=0,
        validation_failed_count=0,
        persistence_failed_count=0,
    )
    assert monitoring_partial_primary_cause(row) == "missing_only"
    assert monitoring_execution_error_count(row) == 0
    detail = monitoring_cycle_status_detail(row)
    assert detail is not None
    assert "missing" in detail.lower() or "YouTube" in detail


def test_execution_errors_partial() -> None:
    row = _Row(
        cycle_status="partial",
        missing_count=0,
        fetch_failed_count=2,
        validation_failed_count=0,
        persistence_failed_count=0,
    )
    assert monitoring_partial_primary_cause(row) == "execution_errors"
    assert monitoring_execution_error_count(row) == 2


if __name__ == "__main__":
    test_missing_only_partial()
    test_execution_errors_partial()
    print("ok")
