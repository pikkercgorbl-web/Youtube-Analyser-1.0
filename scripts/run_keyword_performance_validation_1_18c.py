"""Generate Stage 1.18C keyword performance historical validation artifacts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.db import SessionLocal
from app.services.keyword_performance_validation import run_full_validation, write_artifacts


def main() -> int:
    artifacts_dir = ROOT / "artifacts"
    session = SessionLocal()
    try:
        report = run_full_validation(artifacts_dir, session=session)
    finally:
        session.close()
    hashes = write_artifacts(report, artifacts_dir)
    print(f"Wrote {hashes['json_path']}")
    print(f"  sha256={hashes['json_sha256']}")
    print(f"Wrote {hashes['md_path']}")
    print(f"  sha256={hashes['md_sha256']}")
    print(f"runtime_seconds={report['runtime_seconds']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
