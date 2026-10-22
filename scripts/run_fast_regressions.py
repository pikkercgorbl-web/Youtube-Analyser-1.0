"""Fast deterministic backend regression suite (Stage 1.20C.1 / Stage 3).

No live PostgreSQL/network/YouTube API. Uses in-memory or :memory: SQLite only.
For PostgreSQL integration/concurrency/E2E: scripts/run_postgres_integration_tests.py
Do not add live verify scripts (stage25 verify, format pass live, etc.).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FAST_SCRIPTS: tuple[str, ...] = (
    # Discovery / operations core
    "test_discovery_cli_wiring.py",
    "test_operations_liveness.py",
    "test_stage3_recovery_locks.py",
    "test_keyword_admission_orchestration.py",
    "test_keyword_lifecycle_recommendations.py",
    "test_keyword_lifecycle_calibration.py",
    "test_72h_outcome_coverage.py",
    "test_delayed_outcome_capture.py",
    "test_operations_read_performance.py",
    # Stage 1 — measurement / monitoring
    "test_snapshot_measurement_regression.py",
    "test_monitoring_video_source.py",
    "test_snapshot_collection_policy.py",
    "test_breakout_ranking.py",
    "test_channel_momentum_age_aligned.py",
    # Stage 2 — enrichment selectors / orchestrator (SQLite)
    "test_subscriber_enrichment_selection_regression.py",
    "test_format_enrichment_selection_regression.py",
    "test_radar_enrichment_stage25.py",
    # Attention / Saved Topics / feedback (SQLite)
    "test_attention_engine_1_22a.py",
    "test_attention_persist_fk_1_22a.py",
    "test_attention_feed_1_22b.py",
    "test_attention_pattern_families_1_22b1.py",
    "test_saved_topics_1_22c.py",
    "test_saved_topics_1_22d.py",
    "test_read_model_publish_lock.py",
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
