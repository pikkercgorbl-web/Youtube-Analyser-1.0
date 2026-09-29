"""Run T72 refresh for frozen Stage 1.10C cohort (observation only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.deps import get_youtube_client
from app.services.radar_stage110_t24_refresh import FrozenCohortVerificationError, run_stage110_t72_refresh


def main() -> int:
    artifacts_dir = ROOT / "artifacts"
    try:
        result = run_stage110_t72_refresh(
            artifacts_dir=artifacts_dir,
            client=get_youtube_client(),
            output_dir=artifacts_dir,
        )
    except FrozenCohortVerificationError as exc:
        print(f"FROZEN COHORT VERIFICATION FAILED: {exc}", file=sys.stderr)
        return 2

    report = {
        "t0_reference_timestamp": result["t0_reference_at"].isoformat(),
        "snapshot_timestamp": result["snapshot_at"].isoformat(),
        "actual_elapsed_hours": result["actual_elapsed_hours"],
        "requested_videos": result["counts"]["requested_video_count"],
        "refreshed_videos": result["counts"]["refreshed_count"],
        "missing_videos": result["counts"]["missing_count"],
        "failed_videos": result["counts"]["failed_count"],
        "missing_video_ids": result["missing_video_ids"],
        "failed_video_ids": result["failed_video_ids"],
        "api_batch_count": result["api_batch_count"],
        "output_jsonl": str(result["jsonl_path"]),
        "output_manifest": str(result["manifest_path"]),
        "output_sha256": result["output_sha256"],
        "t0_artifacts_unchanged": result["t0_artifacts_unchanged"],
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
