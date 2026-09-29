"""Offline verification of Stage 1.10C T0 freeze artifact."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARTIFACTS = ROOT / "artifacts"
RUN_ID = "stage110_20260914_141029"
PREFIX = f"cohort_T0_{RUN_ID}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_freeze_invariants() -> None:
    freeze_path = ARTIFACTS / f"{PREFIX}_freeze.json"
    audit_path = ARTIFACTS / f"{PREFIX}_failed_audit.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    assert freeze["sample_row_count"] == 500
    assert freeze["failed_baseline_count"] == 6
    assert audit["failed_total"] == 6
    assert freeze["leakage_violation_count"] == 0

    assert sha256_file(Path(freeze["broad_path"])) == freeze["broad_sha256"]
    assert sha256_file(Path(freeze["sample_path"])) == freeze["sample_sha256"]
    assert sha256_file(Path(freeze["t0_manifest_path"])) == freeze["manifest_sha256"]

    sample_ids = [
        json.loads(line)["video_id"]
        for line in Path(freeze["sample_path"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(sample_ids) == len(set(sample_ids))
    assert sample_ids == freeze["frozen_sample_video_ids"]


if __name__ == "__main__":
    test_freeze_invariants()
    print("OK test_stage110_t0_freeze")
