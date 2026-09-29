"""Generate Stage 1.17C breakout_v1 historical evaluation artifacts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.breakout_rank_v1_evaluation import run_full_evaluation, write_artifacts


def main() -> int:
    artifacts_dir = ROOT / "artifacts"
    report = run_full_evaluation(artifacts_dir)
    hashes = write_artifacts(report, artifacts_dir)
    print(f"Wrote {hashes['json_path']}")
    print(f"  sha256={hashes['json_sha256']}")
    print(f"Wrote {hashes['md_path']}")
    print(f"  sha256={hashes['md_sha256']}")
    print(f"acceptance_pass={report['acceptance']['pass']}")
    return 0 if report["acceptance"]["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
