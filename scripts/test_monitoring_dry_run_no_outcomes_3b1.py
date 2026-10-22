"""Dry-run monitoring cycle must not call YouTube client or write capture outcomes."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.monitoring_cycle import run_monitoring_cycle
from app.services.metrics import ensure_utc


def test_dry_run_no_fetch_no_outcomes_persist() -> None:
    session = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.flush = MagicMock()
    client = MagicMock()

    empty_summary = MagicMock()
    empty_summary.cycle_status = "dry_run"
    empty_summary.missing_retry_suppressed_count = 0

    with patch(
        "app.services.monitoring_cycle.load_monitored_video_states",
        return_value=[],
    ):
        summary = run_monitoring_cycle(
            session,
            youtube_client=client,
            dry_run=True,
            current_time=ensure_utc(datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)),
        )

    assert summary.cycle_status == "dry_run"
    client.get_videos.assert_not_called()
    session.commit.assert_not_called()


if __name__ == "__main__":
    test_dry_run_no_fetch_no_outcomes_persist()
    print("ok")
