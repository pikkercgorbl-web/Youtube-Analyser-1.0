"""PostgreSQL-only integration tests (explicit test DB; never production restore-check)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

POSTGRES_SCRIPTS: tuple[str, ...] = (
    "test_radar_api_budget_concurrency.py",
    "test_read_model_publish_lock_postgres.py",
    "test_saved_topics_1_22c_postgres_regression.py",
    "test_observation_readiness_e2e.py",
)


def _guard_urls() -> None:
    test_url = (
        os.environ.get("RADAR_BUDGET_POSTGRES_TEST_URL", "").strip()
        or os.environ.get("SAVED_TOPICS_POSTGRES_TEST_URL", "").strip()
    )
    prod = os.environ.get("DATABASE_URL", "").strip()
    if not test_url and not os.environ.get("SAVED_TOPICS_POSTGRES_TEST_URL"):
        raise SystemExit(
            "Set SAVED_TOPICS_POSTGRES_TEST_URL (and optionally RADAR_BUDGET_POSTGRES_TEST_URL) "
            "to a dedicated PostgreSQL test database.",
        )
    if prod and "restore_check" in prod.lower() and os.environ.get("ALLOW_RESTORE_CHECK_INTEGRATION") != "1":
        raise SystemExit(
            "Refusing: DATABASE_URL points at restore_check. "
            "Use a *_test database or set ALLOW_RESTORE_CHECK_INTEGRATION=1 for deliberate runs.",
        )


def main() -> int:
    _guard_urls()
    failed: list[str] = []
    for name in POSTGRES_SCRIPTS:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / name)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=900,
        )
        if proc.returncode != 0:
            failed.append(name)
            print(f"FAIL {name}\n{proc.stderr or proc.stdout}", file=sys.stderr)
        else:
            print(f"OK {name}")
    if failed:
        print(f"PostgreSQL integration failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("PostgreSQL integration suite passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
