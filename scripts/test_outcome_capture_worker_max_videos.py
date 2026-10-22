"""Worker CLI and budget wiring for --max-videos (Stage 1.20E.2)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.services.delayed_outcome_capture_config import (
    DEFAULT_OUTCOME_CAPTURE_BATCH_SIZE,
    DEFAULT_OUTCOME_CAPTURE_MAX_VIDEOS_PER_CYCLE,
    OutcomeCaptureBudgetPolicy,
    outcome_capture_budget_for_cycle,
)
from app.services.delayed_outcome_capture_cycle import DelayedOutcomeCaptureCycleSummary
from app.services.delayed_outcome_capture_planner import select_fetch_candidates_for_cycle
from app.services.delayed_outcome_capture_types import OutcomeVideoFetchCandidate
from app.services.metrics import utc_now
from app.services.outcome_capture_worker_runtime import (
    OutcomeCaptureWorkerConfig,
    run_outcome_capture_worker_loop,
)

CLI = ROOT / "scripts" / "run_outcome_capture_worker.py"
NOW = utc_now()


def test_default_cap_is_100_without_override() -> None:
    budget = outcome_capture_budget_for_cycle(max_videos_per_cycle=None)
    assert budget.max_videos_per_cycle == DEFAULT_OUTCOME_CAPTURE_MAX_VIDEOS_PER_CYCLE == 100


def test_override_cap_1000() -> None:
    budget = outcome_capture_budget_for_cycle(max_videos_per_cycle=1000)
    assert budget.max_videos_per_cycle == 1000
    assert budget.batch_size == DEFAULT_OUTCOME_CAPTURE_BATCH_SIZE


def test_override_preserves_di_priority_from_env() -> None:
    import os

    prev = os.environ.get("OUTCOME_CAPTURE_DI_WINNER_PRIORITY")
    os.environ["OUTCOME_CAPTURE_DI_WINNER_PRIORITY"] = "1"
    try:
        budget = outcome_capture_budget_for_cycle(max_videos_per_cycle=500)
        assert budget.di_winner_priority_enabled is True
        assert budget.batch_size == DEFAULT_OUTCOME_CAPTURE_BATCH_SIZE
        assert budget.priority_max_slots == 30
        assert budget.background_min_slots == 70
    finally:
        if prev is None:
            os.environ.pop("OUTCOME_CAPTURE_DI_WINNER_PRIORITY", None)
        else:
            os.environ["OUTCOME_CAPTURE_DI_WINNER_PRIORITY"] = prev


def test_worker_cycle_receives_planner_budget_1000() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    seen: dict[str, int] = {}

    def fake_cycle(_session, *, youtube_client, dry_run=False, budget=None, **kwargs):
        seen["max"] = budget.max_videos_per_cycle
        now = NOW
        return DelayedOutcomeCaptureCycleSummary(run_id="t", started_at=now, finished_at=now)

    with patch(
        "app.services.outcome_capture_worker_runtime.run_delayed_outcome_capture_cycle",
        side_effect=fake_cycle,
    ):
        run_outcome_capture_worker_loop(
            factory,
            object(),
            config=OutcomeCaptureWorkerConfig(
                interval_seconds=999,
                max_videos_per_cycle=1000,
            ),
            sleep_fn=lambda _s: None,
            stop_check=lambda: "max" in seen,
        )
    assert seen.get("max") == 1000


def test_cli_rejects_zero_and_negative_max_videos() -> None:
    for bad in ("0", "-1"):
        proc = subprocess.run(
            [sys.executable, str(CLI), "--max-videos", bad],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert proc.returncode != 0, bad
        assert "positive" in (proc.stderr + proc.stdout).lower()


def test_priority_cap_1000_uses_fixed_slots_not_percent() -> None:
    """At cap>100: priority_max_slots stays 30; spare slots go to background."""
    budget = OutcomeCaptureBudgetPolicy(
        max_videos_per_cycle=1000,
        di_winner_priority_enabled=True,
        priority_max_slots=30,
        background_min_slots=70,
    )
    pri_ids = frozenset({f"p{i}" for i in range(50)})
    candidates = [
        OutcomeVideoFetchCandidate(
            video_id=f"p{i}",
            channel_id="ch",
            priority_hours_to_window_end=float(i),
            observation_count=1,
            states=("capture_due",),
            window_end=NOW,
        )
        for i in range(50)
    ] + [
        OutcomeVideoFetchCandidate(
            video_id=f"b{i}",
            channel_id="ch",
            priority_hours_to_window_end=float(i),
            observation_count=1,
            states=("capture_due",),
            window_end=NOW,
        )
        for i in range(1000)
    ]
    selected, inst = select_fetch_candidates_for_cycle(
        candidates,
        budget=budget,
        di_winner_video_ids=pri_ids,
    )
    assert len(selected) == 1000
    assert inst.priority_selected == 30
    assert inst.background_selected == 970
    assert inst.priority_deferred == 20


def main() -> None:
    tests = [
        test_default_cap_is_100_without_override,
        test_override_cap_1000,
        test_override_preserves_di_priority_from_env,
        test_worker_cycle_receives_planner_budget_1000,
        test_cli_rejects_zero_and_negative_max_videos,
        test_priority_cap_1000_uses_fixed_slots_not_percent,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"OK {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    if failed:
        raise SystemExit(f"{failed} test(s) failed")
    print("All outcome worker max-videos tests passed.")


if __name__ == "__main__":
    main()
