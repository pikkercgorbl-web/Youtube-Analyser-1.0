"""LIVE discovery CLI smoke (Stage 1.20C.1).

Requires configured DATABASE_URL, network, and YouTube/InnerTube availability.
NOT part of fast regression — run manually or in a dedicated CI job.

  python scripts/test_discovery_cli_live.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT_SECONDS = 180


def main() -> int:
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_discovery_cycle.py"),
            "--dry-run",
            "--batch-size",
            "1",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
    )
    if proc.returncode not in (0, 1):
        print(proc.stderr or proc.stdout, file=sys.stderr)
        return proc.returncode or 2
    if "run_id" not in proc.stdout:
        print("Expected run_id in stdout:", proc.stdout, file=sys.stderr)
        return 3
    print("Live discovery CLI smoke OK")
    print(proc.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
