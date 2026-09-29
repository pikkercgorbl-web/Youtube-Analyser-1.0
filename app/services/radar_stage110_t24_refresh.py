"""Temporal checkpoint refresh for frozen Stage 1.10C cohort (observation only)."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.integrations.youtube.client import YouTubeVideoDetails
from app.services.metrics import ensure_utc
from app.services.radar_t0_data_quality import load_t0_jsonl
from app.services.radar_t72_refresh import (
    T0ArtifactFingerprint,
    calc_elapsed_hours,
    file_fingerprint,
    refresh_video_details,
    t0_artifacts_unchanged,
)

EXPERIMENT_ID = "stage110_20260914_141029"
EXPECTED_SAMPLE_ROWS = 500
BATCH_SIZE = 50

REFRESH_SCHEMA_VERSION = "1.10C_T24"
CHECKPOINT_LABEL = "T24"
TARGET_CHECKPOINT_HOURS = 24


@dataclass(frozen=True, slots=True)
class Stage110Checkpoint:
    label: str
    target_hours: int
    schema_version: str


T24_CHECKPOINT = Stage110Checkpoint("T24", 24, "1.10C_T24")
T48_CHECKPOINT = Stage110Checkpoint("T48", 48, "1.10C_T48")
T72_CHECKPOINT = Stage110Checkpoint("T72", 72, "1.10C_T72")

FROZEN_HASHES = {
    "broad": "3ded1f61efdb4d2d7ac504bf078ebdb5799e7459cb44a58afaf50159075ffe0a",
    "sample": "7fcade5724ca2b556aa86317f3110f8cea0a91c58c8e74863abb76c4fa122cc7",
    "manifest": "3034e8c1d049e6a0d43b596b258ede9734d60ce54b4673ee7f222e1671680ccd",
}


class FrozenCohortVerificationError(Exception):
    """Frozen artifact mismatch — refresh must not proceed."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_freeze_metadata(freeze_path: Path) -> dict[str, Any]:
    return json.loads(freeze_path.read_text(encoding="utf-8"))


def verify_frozen_artifacts(
    *,
    artifacts_dir: Path,
    freeze_path: Path | None = None,
) -> dict[str, Any]:
    freeze_path = freeze_path or artifacts_dir / f"cohort_T0_{EXPERIMENT_ID}_freeze.json"
    freeze = load_freeze_metadata(freeze_path)

    paths = {
        "broad": Path(freeze["broad_path"]),
        "sample": Path(freeze["sample_path"]),
        "manifest": Path(freeze["t0_manifest_path"]),
    }
    observed: dict[str, str] = {}
    for key, path in paths.items():
        if not path.is_file():
            raise FrozenCohortVerificationError(f"Missing frozen artifact: {path}")
        observed[key] = sha256_file(path)

    expected = {
        "broad": freeze.get("broad_sha256", FROZEN_HASHES["broad"]),
        "sample": freeze.get("sample_sha256", FROZEN_HASHES["sample"]),
        "manifest": freeze.get("manifest_sha256", FROZEN_HASHES["manifest"]),
    }
    for key in ("broad", "sample", "manifest"):
        if observed[key] != expected[key]:
            raise FrozenCohortVerificationError(
                f"Hash mismatch for {key}: expected {expected[key]} got {observed[key]}",
            )

    sample_rows = load_t0_jsonl(paths["sample"])
    if len(sample_rows) != EXPECTED_SAMPLE_ROWS:
        raise FrozenCohortVerificationError(
            f"Sample row count {len(sample_rows)} != expected {EXPECTED_SAMPLE_ROWS}",
        )

    sample_ids = [str(row["video_id"]) for row in sample_rows]
    if len(set(sample_ids)) != len(sample_ids):
        raise FrozenCohortVerificationError("Duplicate video_id in frozen sample")

    frozen_ids = freeze.get("frozen_sample_video_ids") or []
    if len(frozen_ids) != EXPECTED_SAMPLE_ROWS:
        raise FrozenCohortVerificationError("frozen_sample_video_ids length mismatch")
    if set(sample_ids) != set(frozen_ids):
        raise FrozenCohortVerificationError("Sample video IDs do not match freeze metadata list")

    return {
        "freeze": freeze,
        "paths": paths,
        "sample_rows": sample_rows,
        "sample_sha256": observed["sample"],
        "fingerprints_before": [
            file_fingerprint(paths["broad"]),
            file_fingerprint(paths["sample"]),
            file_fingerprint(paths["manifest"]),
            file_fingerprint(freeze_path),
        ],
    }


def parse_t0_reference_timestamp(manifest_path: Path) -> datetime:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw = manifest.get("discovery_timestamp") or manifest.get("timestamp")
    if not raw:
        raise FrozenCohortVerificationError("T0 reference timestamp missing from manifest")
    return ensure_utc(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))


def _views_t0(row: dict[str, Any]) -> int | None:
    if row.get("t0_views") is not None:
        return int(row["t0_views"])
    if row.get("discovery_views") is not None:
        return int(row["discovery_views"])
    return None


def _relative_growth(t0_views: int | None, current_views: int | None) -> float | None:
    if t0_views is None or current_views is None or t0_views <= 0:
        return None
    return round((current_views - t0_views) / t0_views, 6)


def _age_hours_current(published_at: datetime | None, snapshot_at: datetime) -> float | None:
    if published_at is None:
        return None
    pub = ensure_utc(published_at)
    snap = ensure_utc(snapshot_at)
    hours = (snap - pub).total_seconds() / 3600.0
    return round(max(hours, 0.0), 4)


def _lifetime_vph(views: int | None, age_hours: float | None) -> float | None:
    if views is None or age_hours is None or age_hours <= 0:
        return None
    return round(views / age_hours, 4)


def build_stage110_refresh_record(
    t0_row: dict[str, Any],
    *,
    snapshot_at: datetime,
    t0_reference_at: datetime,
    actual_elapsed_hours: float,
    details: YouTubeVideoDetails | None,
    fetch_status: str,
    checkpoint: Stage110Checkpoint = T24_CHECKPOINT,
) -> dict[str, Any]:
    """Preserve frozen T0 row; append factual refresh fields only."""
    record = deepcopy(t0_row)
    views_t0 = _views_t0(t0_row)
    current_views = details.views_count if details is not None else None
    published_at = details.published_at if details is not None else None
    age_current = _age_hours_current(published_at, snapshot_at)

    absolute_growth = None
    if views_t0 is not None and current_views is not None:
        absolute_growth = current_views - views_t0

    record.update(
        {
            "schema_version": checkpoint.schema_version,
            "experiment_id": EXPERIMENT_ID,
            "checkpoint_label": checkpoint.label,
            "target_checkpoint_hours": checkpoint.target_hours,
            "t0_reference_timestamp": ensure_utc(t0_reference_at).isoformat(),
            "snapshot_captured_at": ensure_utc(snapshot_at).isoformat(),
            "actual_elapsed_hours": actual_elapsed_hours,
            "fetch_status": fetch_status,
            "views_t0": views_t0,
            "views_current": current_views,
            "absolute_view_growth": absolute_growth,
            "relative_view_growth": _relative_growth(views_t0, current_views),
            "current_likes": details.likes_count if details else None,
            "current_comments": details.comments_count if details else None,
            "current_published_at": published_at.isoformat() if published_at else None,
            "current_duration_seconds": details.duration_seconds if details else None,
            "current_title": details.title if details else None,
            "current_channel_id": details.channel_id if details else None,
            "age_hours_current": age_current,
            "current_lifetime_vph": _lifetime_vph(current_views, age_current),
            "elapsed_hours_from_t0": actual_elapsed_hours,
        },
    )
    return record


def verify_refresh_output(
    *,
    sample_rows: list[dict[str, Any]],
    output_records: list[dict[str, Any]],
    counts: dict[str, int],
) -> dict[str, Any]:
    sample_ids = [str(r["video_id"]) for r in sample_rows]
    out_ids = [str(r["video_id"]) for r in output_records]
    expected = len(sample_rows)
    ids_match = sample_ids == out_ids
    unique_ok = len(out_ids) == len(set(out_ids)) == expected
    accounting_ok = counts["refreshed"] + counts["missing"] + counts["failed"] == expected
    baseline_ok = True
    for src, out in zip(sample_rows, output_records, strict=True):
        for key, value in src.items():
            if out.get(key) != value:
                baseline_ok = False
                break

    no_fake_zeros = True
    for row in output_records:
        if row.get("fetch_status") == "missing":
            if row.get("views_current") == 0:
                no_fake_zeros = False

    return {
        "requested_ids_match_sample_order": ids_match,
        "sample_count_unchanged": len(output_records) == expected,
        "no_duplicate_video_ids": unique_ok,
        "accounting_ok": accounting_ok,
        "baseline_fields_unchanged": baseline_ok,
        "no_fake_zero_views_on_missing": no_fake_zeros,
        "all_ok": ids_match and unique_ok and accounting_ok and baseline_ok and no_fake_zeros,
    }


def export_checkpoint_artifacts(
    records: list[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    checkpoint: Stage110Checkpoint,
    output_dir: Path,
    snapshot_at: datetime,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = ensure_utc(snapshot_at).strftime("%Y%m%d_%H%M%S")
    jsonl_path = output_dir / f"cohort_{checkpoint.label}_{EXPERIMENT_ID}_{stamp}.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")
    output_sha = sha256_file(jsonl_path)
    manifest["output_jsonl_path"] = str(jsonl_path.resolve())
    manifest["output_sha256"] = output_sha
    manifest_path = output_dir / f"cohort_{checkpoint.label}_{EXPERIMENT_ID}_{stamp}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonl_path, manifest_path


def export_t24_artifacts(
    records: list[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    output_dir: Path,
    snapshot_at: datetime,
) -> tuple[Path, Path]:
    return export_checkpoint_artifacts(
        records,
        manifest,
        checkpoint=T24_CHECKPOINT,
        output_dir=output_dir,
        snapshot_at=snapshot_at,
    )


def run_stage110_checkpoint_refresh(
    *,
    checkpoint: Stage110Checkpoint,
    artifacts_dir: Path,
    client,
    output_dir: Path | None = None,
    snapshot_at: datetime | None = None,
) -> dict[str, Any]:
    """
    Refresh frozen 500-video sample via YouTube Data API. No DB writes. No T0 mutation.
    """
    output_dir = output_dir or artifacts_dir
    verified = verify_frozen_artifacts(artifacts_dir=artifacts_dir)
    sample_rows: list[dict[str, Any]] = verified["sample_rows"]
    fingerprints_before: list[T0ArtifactFingerprint] = verified["fingerprints_before"]

    manifest_path: Path = verified["paths"]["manifest"]
    t0_reference_at = parse_t0_reference_timestamp(manifest_path)
    snapshot = snapshot_at or datetime.now(timezone.utc)
    actual_elapsed_hours = calc_elapsed_hours(t0_reference_at, snapshot)

    video_ids = [str(row["video_id"]) for row in sample_rows]
    details_by_id, batch_count, failed_ids = refresh_video_details(client, video_ids)

    refreshed = missing = failed = 0
    records: list[dict[str, Any]] = []
    for row in sample_rows:
        video_id = str(row["video_id"])
        if video_id in failed_ids:
            status = "failed"
            details = None
            failed += 1
        elif video_id in details_by_id:
            status = "refreshed"
            details = details_by_id[video_id]
            refreshed += 1
        else:
            status = "missing"
            details = None
            missing += 1
        records.append(
            build_stage110_refresh_record(
                row,
                snapshot_at=snapshot,
                t0_reference_at=t0_reference_at,
                actual_elapsed_hours=actual_elapsed_hours,
                details=details,
                fetch_status=status,
                checkpoint=checkpoint,
            ),
        )

    counts = {
        "requested_video_count": len(video_ids),
        "refreshed_count": refreshed,
        "missing_count": missing,
        "failed_count": failed,
    }
    invariants = verify_refresh_output(
        sample_rows=sample_rows,
        output_records=records,
        counts={
            "refreshed": refreshed,
            "missing": missing,
            "failed": failed,
        },
    )
    if not invariants["all_ok"]:
        raise FrozenCohortVerificationError(f"Refresh invariants failed: {invariants}")

    fingerprints_after = [
        file_fingerprint(Path(item.path)) for item in fingerprints_before
    ]
    t0_unchanged = t0_artifacts_unchanged(fingerprints_before, fingerprints_after)

    meta = {
        "schema_version": checkpoint.schema_version,
        "experiment_id": EXPERIMENT_ID,
        "checkpoint_label": checkpoint.label,
        "target_checkpoint_hours": checkpoint.target_hours,
        "t0_reference_timestamp": ensure_utc(t0_reference_at).isoformat(),
        "snapshot_timestamp": ensure_utc(snapshot).isoformat(),
        "actual_elapsed_hours": actual_elapsed_hours,
        "frozen_sample_count": EXPECTED_SAMPLE_ROWS,
        **counts,
        "api_batch_count": batch_count,
        "t0_sample_sha256": verified["sample_sha256"],
        "invariants": invariants,
        "t0_artifacts_unchanged": t0_unchanged,
        "t0_artifact_fingerprints_before": [asdict(x) for x in fingerprints_before],
        "t0_artifact_fingerprints_after": [asdict(x) for x in fingerprints_after],
        "NO_DB_WRITES": True,
        "NO_DISCOVERY": True,
    }

    jsonl_path, manifest_out_path = export_checkpoint_artifacts(
        records,
        meta,
        checkpoint=checkpoint,
        output_dir=output_dir,
        snapshot_at=snapshot,
    )

    missing_ids = [str(r["video_id"]) for r in records if r.get("fetch_status") == "missing"]
    failed_ids_out = [str(r["video_id"]) for r in records if r.get("fetch_status") == "failed"]

    return {
        "checkpoint": checkpoint,
        "t0_reference_at": t0_reference_at,
        "snapshot_at": snapshot,
        "actual_elapsed_hours": actual_elapsed_hours,
        "counts": counts,
        "missing_video_ids": missing_ids,
        "failed_video_ids": failed_ids_out,
        "api_batch_count": batch_count,
        "jsonl_path": jsonl_path,
        "manifest_path": manifest_out_path,
        "output_sha256": meta["output_sha256"],
        "t0_artifacts_unchanged": t0_unchanged,
        "invariants": invariants,
    }


def run_stage110_t24_refresh(
    *,
    artifacts_dir: Path,
    client,
    output_dir: Path | None = None,
    snapshot_at: datetime | None = None,
) -> dict[str, Any]:
    return run_stage110_checkpoint_refresh(
        checkpoint=T24_CHECKPOINT,
        artifacts_dir=artifacts_dir,
        client=client,
        output_dir=output_dir,
        snapshot_at=snapshot_at,
    )


def run_stage110_t48_refresh(
    *,
    artifacts_dir: Path,
    client,
    output_dir: Path | None = None,
    snapshot_at: datetime | None = None,
) -> dict[str, Any]:
    return run_stage110_checkpoint_refresh(
        checkpoint=T48_CHECKPOINT,
        artifacts_dir=artifacts_dir,
        client=client,
        output_dir=output_dir,
        snapshot_at=snapshot_at,
    )


def run_stage110_t72_refresh(
    *,
    artifacts_dir: Path,
    client,
    output_dir: Path | None = None,
    snapshot_at: datetime | None = None,
) -> dict[str, Any]:
    return run_stage110_checkpoint_refresh(
        checkpoint=T72_CHECKPOINT,
        artifacts_dir=artifacts_dir,
        client=client,
        output_dir=output_dir,
        snapshot_at=snapshot_at,
    )
