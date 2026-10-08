"""Offline recovery / lock / idempotency regression bundle (Stage 3)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RECOVERY_SCRIPTS: tuple[str, ...] = (
    "test_stage3_recovery_locks.py",
    "test_read_model_publish_lock.py",
    "test_video_snapshot_storage.py",
    "test_attention_engine_1_22a.py",
)


def main() -> int:
    failed: list[str] = []
    for name in RECOVERY_SCRIPTS:
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
        print(f"Stage 3 recovery suite failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("Stage 3 recovery suite passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
