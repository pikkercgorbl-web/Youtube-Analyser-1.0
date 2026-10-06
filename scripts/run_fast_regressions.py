"""Fast deterministic backend regression suite (Stage 1.20C.1).

No live PostgreSQL/network/InnerTube. For live discovery smoke use test_discovery_cli_live.py.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Scripts that must complete without external services (each is self-contained).
FAST_SCRIPTS: tuple[str, ...] = (
    "test_discovery_cli_wiring.py",
    "test_operations_liveness.py",
    "test_discovery_cycle.py",
    "test_discovery_worker.py",
    "test_keyword_admission_orchestration.py",
    "test_keyword_lifecycle_recommendations.py",
    "test_keyword_lifecycle_calibration.py",
    "test_72h_outcome_coverage.py",
    "test_delayed_outcome_capture.py",
    "test_operations_read_performance.py",
    "test_attention_engine_1_22a.py",
    "test_attention_persist_fk_1_22a.py",
    "test_attention_feed_1_22b.py",
    "test_attention_pattern_families_1_22b1.py",
)


def main() -> int:
    failed: list[str] = []
    for name in FAST_SCRIPTS:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / name)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=600,
        )
        if proc.returncode != 0:
            failed.append(name)
            print(f"FAIL {name}\n{proc.stderr or proc.stdout}", file=sys.stderr)
        else:
            print(f"OK {name}")
    if failed:
        print(f"Fast regression failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("Fast regression suite passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
