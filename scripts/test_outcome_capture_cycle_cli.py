"""CLI regression tests for scripts/run_outcome_capture_cycle.py (Stage 1.23C.1A)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "run_outcome_capture_cycle.py"
CYCLE_SCRIPT = ROOT / "scripts" / "test_delayed_outcome_capture.py"


def _bootstrap_sqlite_env(db_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    env["DEBUG"] = "true"
    env["RADAR_SQL_ECHO"] = "true"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _create_sqlite_schema(env: dict[str, str]) -> None:
    bootstrap = (
        "import sys; from pathlib import Path; "
        f"ROOT=Path({str(ROOT)!r}); sys.path.insert(0, str(ROOT)); "
        "import app.models.orm; from app.models.db import Base, engine; "
        "Base.metadata.create_all(engine)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", bootstrap],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"schema bootstrap failed: {proc.stderr}")


def test_json_stdout_is_single_valid_document() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "cli_test.db"
        env = _bootstrap_sqlite_env(db)
        _create_sqlite_schema(env)
        proc = subprocess.run(
            [sys.executable, str(CLI), "--dry-run", "--json"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip(), "expected JSON on stdout"
        payload = json.loads(proc.stdout)
        assert payload.get("cycle_status") == "dry_run"
        assert "selection" in payload


def test_json_stdout_has_no_sqlalchemy_info() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "cli_test.db"
        env = _bootstrap_sqlite_env(db)
        _create_sqlite_schema(env)
        proc = subprocess.run(
            [sys.executable, str(CLI), "--dry-run", "--json"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert proc.returncode == 0, proc.stderr
        upper = proc.stdout.upper()
        assert "SELECT " not in upper
        assert "INFO:SQLALCHEMY" not in upper.replace(" ", "")
        assert "INSERT INTO" not in upper


def test_cli_error_nonzero_exit_and_stderr() -> None:
    env = _bootstrap_sqlite_env(Path(tempfile.gettempdir()) / "missing_schema.db")
    proc = subprocess.run(
        [sys.executable, str(CLI), "--dry-run", "--json"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode != 0
    assert proc.stderr.strip()


def test_off_on_budget_invariants_via_unit() -> None:
    sys.path.insert(0, str(ROOT))
    from datetime import datetime, timedelta, timezone

    from app.services.delayed_outcome_capture_config import OutcomeCaptureBudgetPolicy
    from app.services.delayed_outcome_capture_planner import select_fetch_candidates_for_cycle
    from app.services.delayed_outcome_capture_types import OutcomeVideoFetchCandidate

    utc = timezone.utc
    now = datetime(2026, 6, 1, 12, 0, tzinfo=utc)
    budget_off = OutcomeCaptureBudgetPolicy(di_winner_priority_enabled=False)
    budget_on = OutcomeCaptureBudgetPolicy(di_winner_priority_enabled=True)

    pri_ids = frozenset({f"p{i}" for i in range(40)})
    candidates = [
        OutcomeVideoFetchCandidate(
            video_id=f"p{i}",
            channel_id="ch",
            priority_hours_to_window_end=float(i),
            observation_count=1,
            states=("capture_due",),
            window_end=now + timedelta(hours=10 - i),
        )
        for i in range(40)
    ] + [
        OutcomeVideoFetchCandidate(
            video_id=f"b{i}",
            channel_id="ch",
            priority_hours_to_window_end=float(i),
            observation_count=1,
            states=("capture_due",),
            window_end=now + timedelta(hours=20),
        )
        for i in range(80)
    ]

    off_sel, off_inst = select_fetch_candidates_for_cycle(
        candidates,
        budget=budget_off,
        di_winner_video_ids=pri_ids,
    )
    on_sel, on_inst = select_fetch_candidates_for_cycle(
        candidates,
        budget=budget_on,
        di_winner_video_ids=pri_ids,
    )

    assert len(off_sel) <= 100
    assert off_inst.priority_selected == 0
    assert off_inst.background_selected == len(off_sel)

    assert len(on_sel) <= 100
    assert on_inst.priority_selected <= 30
    assert on_inst.background_selected >= 70
    assert len({row.video_id for row in on_sel if row.is_di_winner_priority}) == on_inst.priority_selected
    assert len(on_sel) == on_inst.priority_selected + on_inst.background_selected


def test_priority_candidates_not_duplicated_in_selection() -> None:
    sys.path.insert(0, str(ROOT))
    from datetime import datetime, timedelta, timezone

    from app.services.delayed_outcome_capture_config import OutcomeCaptureBudgetPolicy
    from app.services.delayed_outcome_capture_planner import select_fetch_candidates_for_cycle
    from app.services.delayed_outcome_capture_types import OutcomeVideoFetchCandidate

    utc = timezone.utc
    now = datetime(2026, 6, 1, 12, 0, tzinfo=utc)
    candidates = [
        OutcomeVideoFetchCandidate(
            video_id="p1",
            channel_id="ch",
            priority_hours_to_window_end=1.0,
            observation_count=2,
            states=("capture_due", "capture_overdue"),
            window_end=now + timedelta(hours=5),
        ),
        OutcomeVideoFetchCandidate(
            video_id="b1",
            channel_id="ch",
            priority_hours_to_window_end=2.0,
            observation_count=1,
            states=("capture_due",),
            window_end=now + timedelta(hours=6),
        ),
    ]
    selected, _ = select_fetch_candidates_for_cycle(
        candidates,
        budget=OutcomeCaptureBudgetPolicy(di_winner_priority_enabled=True),
        di_winner_video_ids=frozenset({"p1"}),
    )
    assert len(selected) == len({row.video_id for row in selected})


def main() -> None:
    tests = [
        test_json_stdout_is_single_valid_document,
        test_json_stdout_has_no_sqlalchemy_info,
        test_cli_error_nonzero_exit_and_stderr,
        test_off_on_budget_invariants_via_unit,
        test_priority_candidates_not_duplicated_in_selection,
    ]
    for fn in tests:
        fn()
        print(f"OK {fn.__name__}")
    print(f"All {len(tests)} CLI tests passed.")

    print("Running scripts/test_delayed_outcome_capture.py ...")
    proc = subprocess.run(
        [sys.executable, str(CYCLE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        raise SystemExit(proc.returncode)
    print(proc.stdout.strip())


if __name__ == "__main__":
    main()
