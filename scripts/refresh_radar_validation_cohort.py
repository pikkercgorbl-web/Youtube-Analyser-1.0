"""Refresh frozen T0 validation cohort at T72+ checkpoint (Stage 1.9C)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.deps import get_youtube_client
from app.core.config import settings
from app.services.radar_t72_refresh import (
    fingerprint_t0_artifacts,
    load_manifest,
    run_t72_refresh,
)

ARTIFACTS_DIR = ROOT / "artifacts"
DEFAULT_MANIFEST = ARTIFACTS_DIR / "cohort_T0_20260911_173903_manifest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh current YouTube state for unique videos in a frozen T0 cohort manifest.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=f"Frozen T0 manifest path (default: {DEFAULT_MANIFEST})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ARTIFACTS_DIR,
        help="Directory for T72 snapshot JSONL/meta.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.manifest.is_file():
        raise SystemExit(f"Manifest not found: {args.manifest}")
    if not settings.youtube_api_keys:
        raise SystemExit("YouTube API keys not configured.")

    manifest = load_manifest(args.manifest)
    t0_before = fingerprint_t0_artifacts(manifest, args.manifest)

    client = get_youtube_client()
    jsonl_path, meta_path, summary = run_t72_refresh(
        args.manifest,
        client=client,
        output_dir=args.output_dir,
        t0_fingerprints_before=t0_before,
    )
    meta = summary["meta"]

    print("[RADAR_T72_REFRESH]", flush=True)
    print(f"T0 reference: {meta['t0_reference_at']}", flush=True)
    print(f"Snapshot at: {meta['snapshot_at']}", flush=True)
    print(f"Elapsed hours: {meta['elapsed_hours_from_t0']}", flush=True)
    print("", flush=True)
    print(f"T0 rows: {meta['t0_rows']}", flush=True)
    print(f"Unique videos: {meta['unique_video_ids']}", flush=True)
    print(f"Cross-keyword duplicates collapsed: {meta['cross_keyword_duplicates_collapsed']}", flush=True)
    print("", flush=True)
    print(f"Refreshed: {meta['refreshed']}", flush=True)
    print(f"Missing: {meta['missing']}", flush=True)
    print(f"Failed: {meta['failed']}", flush=True)
    print("", flush=True)
    print("Output:", flush=True)
    print(jsonl_path, flush=True)
    print(meta_path, flush=True)
    print("", flush=True)
    print(f"NO_DB_WRITES: {meta['NO_DB_WRITES']}", flush=True)
    print(f"T0_ARTIFACTS_MODIFIED: {meta['T0_ARTIFACTS_MODIFIED']}", flush=True)

    if not meta["invariants"]["all_ok"]:
        raise SystemExit("Refresh invariants failed — inspect meta.json")


if __name__ == "__main__":
    main()
