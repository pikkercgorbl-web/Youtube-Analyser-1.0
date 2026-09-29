"""T72+ refresh snapshot for frozen T0 validation cohort (Stage 1.9C)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.integrations.youtube.client import YouTubeVideoDetails
from app.services.metrics import ensure_utc
from app.services.radar_t0_data_quality import load_t0_jsonl

REFRESH_SCHEMA_VERSION = "1.9C"
T0_REFERENCE_FALLBACK = datetime(2026, 9, 11, 17, 39, 3, tzinfo=timezone.utc)
BATCH_SIZE = 50


class VideoRefreshClient(Protocol):
    def get_videos(self, video_ids: list[str]) -> list[YouTubeVideoDetails]:
        ...


@dataclass(frozen=True, slots=True)
class T0ArtifactFingerprint:
    path: str
    sha256: str
    size_bytes: int


def file_fingerprint(path: Path) -> T0ArtifactFingerprint:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return T0ArtifactFingerprint(path=str(path.resolve()), sha256=digest, size_bytes=path.stat().st_size)


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def collect_t0_artifact_paths(manifest: dict[str, Any], manifest_path: Path) -> list[Path]:
    paths = [manifest_path]
    for entry in manifest.get("per_keyword", []):
        dataset_path = entry.get("dataset_path")
        if dataset_path:
            paths.append(Path(dataset_path))
        meta_path = entry.get("meta_path")
        if meta_path:
            paths.append(Path(meta_path))
    return paths


def fingerprint_t0_artifacts(manifest: dict[str, Any], manifest_path: Path) -> list[T0ArtifactFingerprint]:
    fingerprints: list[T0ArtifactFingerprint] = []
    for path in collect_t0_artifact_paths(manifest, manifest_path):
        if path.is_file():
            fingerprints.append(file_fingerprint(path))
    return fingerprints


def t0_artifacts_unchanged(
    before: list[T0ArtifactFingerprint],
    after: list[T0ArtifactFingerprint],
) -> bool:
    before_by_path = {item.path: item for item in before}
    after_by_path = {item.path: item for item in after}
    if before_by_path.keys() != after_by_path.keys():
        return False
    for path, item in before_by_path.items():
        other = after_by_path[path]
        if item.sha256 != other.sha256 or item.size_bytes != other.size_bytes:
            return False
    return True


def load_t0_rows_from_manifest(manifest_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = load_manifest(manifest_path)
    rows: list[dict[str, Any]] = []
    for entry in manifest.get("per_keyword", []):
        dataset_path = Path(entry["dataset_path"])
        rows.extend(load_t0_jsonl(dataset_path))
    return manifest, rows


def parse_t0_reference_at(manifest: dict[str, Any]) -> datetime:
    raw = manifest.get("timestamp")
    if raw:
        return ensure_utc(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
    return T0_REFERENCE_FALLBACK


def build_unique_refresh_cohort(t0_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Collapse cross-keyword duplicates to one row per video_id."""
    by_video: dict[str, list[dict[str, Any]]] = {}
    for row in t0_rows:
        video_id = row.get("video_id")
        if not video_id:
            continue
        by_video.setdefault(str(video_id), []).append(row)

    unique_records: list[dict[str, Any]] = []
    for video_id in sorted(by_video.keys()):
        occurrences = sorted(by_video[video_id], key=lambda item: str(item.get("keyword", "")))
        primary = occurrences[0]
        keywords = sorted({str(item.get("keyword", "")) for item in occurrences if item.get("keyword")})
        unique_records.append(
            {
                "video_id": video_id,
                "t0_keywords": keywords,
                "t0_row_occurrences": len(occurrences),
                "t0_discovered_at": primary.get("discovered_at"),
                "t0_discovery_views": primary.get("discovery_views"),
                "t0_final_subscribers": primary.get("final_subscribers"),
                "t0_published_at": primary.get("published_at"),
                "t0_age_hours": primary.get("age_hours_at_t0"),
                "t0_vph": primary.get("vph_at_t0"),
                "t0_views_per_subscriber": primary.get("views_per_subscriber_at_t0"),
                "t0_content_format": primary.get("content_format"),
                "t0_qualification_outcome": primary.get("qualification_state"),
                "t0_filter_reason": primary.get("first_failure_reason"),
            },
        )

    stats = {
        "t0_rows": len(t0_rows),
        "unique_video_ids": len(unique_records),
        "cross_keyword_duplicates_collapsed": len(t0_rows) - len(unique_records),
    }
    return unique_records, stats


def calc_elapsed_hours(t0_reference_at: datetime, snapshot_at: datetime) -> float:
    ref = ensure_utc(t0_reference_at)
    snap = ensure_utc(snapshot_at)
    return round((snap - ref).total_seconds() / 3600.0, 4)


def calc_growth_fields(
    *,
    t0_views: int | None,
    current_views: int | None,
    elapsed_hours_from_t0: float,
) -> dict[str, Any]:
    if t0_views is None or current_views is None:
        return {
            "t0_views": t0_views,
            "current_views": current_views,
            "absolute_view_growth": None,
            "view_growth_multiple": None,
            "avg_growth_views_per_hour": None,
        }

    absolute = current_views - t0_views
    multiple = round(current_views / t0_views, 4) if t0_views > 0 else None
    avg_per_hour = (
        round(absolute / elapsed_hours_from_t0, 4)
        if elapsed_hours_from_t0 > 0
        else None
    )
    return {
        "t0_views": t0_views,
        "current_views": current_views,
        "absolute_view_growth": absolute,
        "view_growth_multiple": multiple,
        "avg_growth_views_per_hour": avg_per_hour,
    }


def refresh_video_details(
    client: VideoRefreshClient,
    video_ids: list[str],
) -> tuple[dict[str, YouTubeVideoDetails], int, set[str]]:
    """Fetch current video details in batches; return map, batch count, failed ids."""
    details_by_id: dict[str, YouTubeVideoDetails] = {}
    failed_ids: set[str] = set()
    batch_count = 0

    for chunk_start in range(0, len(video_ids), BATCH_SIZE):
        chunk = video_ids[chunk_start : chunk_start + BATCH_SIZE]
        batch_count += 1
        try:
            for details in client.get_videos(chunk):
                details_by_id[details.video_id] = details
        except Exception:
            failed_ids.update(chunk)

    return details_by_id, batch_count, failed_ids


def build_refresh_record(
    cohort_row: dict[str, Any],
    *,
    snapshot_at: datetime,
    t0_reference_at: datetime,
    elapsed_hours_from_t0: float,
    details: YouTubeVideoDetails | None,
    refresh_status: str,
) -> dict[str, Any]:
    t0_views = cohort_row.get("t0_discovery_views")
    if t0_views is not None:
        t0_views = int(t0_views)

    current_views = details.views_count if details is not None else None
    growth = calc_growth_fields(
        t0_views=t0_views,
        current_views=current_views,
        elapsed_hours_from_t0=elapsed_hours_from_t0,
    )

    record: dict[str, Any] = {
        "video_id": cohort_row["video_id"],
        "t0_keywords": cohort_row["t0_keywords"],
        "t0_row_occurrences": cohort_row["t0_row_occurrences"],
        "t0_discovered_at": cohort_row.get("t0_discovered_at"),
        "t0_discovery_views": cohort_row.get("t0_discovery_views"),
        "t0_final_subscribers": cohort_row.get("t0_final_subscribers"),
        "t0_published_at": cohort_row.get("t0_published_at"),
        "t0_age_hours": cohort_row.get("t0_age_hours"),
        "t0_vph": cohort_row.get("t0_vph"),
        "t0_views_per_subscriber": cohort_row.get("t0_views_per_subscriber"),
        "t0_content_format": cohort_row.get("t0_content_format"),
        "t0_qualification_outcome": cohort_row.get("t0_qualification_outcome"),
        "t0_filter_reason": cohort_row.get("t0_filter_reason"),
        "snapshot_at": ensure_utc(snapshot_at).isoformat(),
        "t0_reference_at": ensure_utc(t0_reference_at).isoformat(),
        "elapsed_hours_from_t0": elapsed_hours_from_t0,
        "refresh_status": refresh_status,
        "current_published_at": details.published_at.isoformat() if details else None,
        "current_duration_seconds": details.duration_seconds if details else None,
        "current_title": details.title if details else None,
        "current_channel_id": details.channel_id if details else None,
    }
    record.update(growth)
    return record


def build_refresh_snapshot(
    cohort_rows: list[dict[str, Any]],
    *,
    details_by_id: dict[str, YouTubeVideoDetails],
    failed_ids: set[str],
    snapshot_at: datetime,
    t0_reference_at: datetime,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    elapsed_hours = calc_elapsed_hours(t0_reference_at, snapshot_at)
    refreshed = missing = failed = 0
    records: list[dict[str, Any]] = []

    for row in cohort_rows:
        video_id = row["video_id"]
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
            build_refresh_record(
                row,
                snapshot_at=snapshot_at,
                t0_reference_at=t0_reference_at,
                elapsed_hours_from_t0=elapsed_hours,
                details=details,
                refresh_status=status,
            ),
        )

    counts = {
        "refreshed": refreshed,
        "missing": missing,
        "failed": failed,
        "unique_video_ids": len(cohort_rows),
    }
    return records, counts


def verify_refresh_invariants(records: list[dict[str, Any]], counts: dict[str, int]) -> dict[str, Any]:
    unique = len(records)
    accounting_ok = unique == counts["refreshed"] + counts["missing"] + counts["failed"]
    growth_ok = True
    growth_violations = 0

    for record in records:
        if record.get("refresh_status") != "refreshed":
            continue
        t0_views = record.get("t0_views")
        current_views = record.get("current_views")
        expected_abs = record.get("absolute_view_growth")
        if t0_views is None or current_views is None or expected_abs is None:
            continue
        if expected_abs != current_views - t0_views:
            growth_ok = False
            growth_violations += 1

    output_rows_ok = unique == counts["unique_video_ids"]

    return {
        "output_rows_equals_unique_video_ids": output_rows_ok,
        "accounting_ok": accounting_ok,
        "growth_sanity_ok": growth_ok,
        "growth_sanity_violations": growth_violations,
        "all_ok": accounting_ok and growth_ok and output_rows_ok,
    }


def export_refresh_snapshot(
    records: list[dict[str, Any]],
    *,
    output_dir: Path,
    snapshot_at: datetime,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = ensure_utc(snapshot_at).strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"cohort_T72_{stamp}_snapshot.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")
    return path


def export_refresh_meta(
    meta: dict[str, Any],
    *,
    output_dir: Path,
    snapshot_at: datetime,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = ensure_utc(snapshot_at).strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"cohort_T72_{stamp}_meta.json"
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_t72_refresh(
    manifest_path: Path,
    *,
    client: VideoRefreshClient,
    output_dir: Path,
    snapshot_at: datetime | None = None,
    t0_fingerprints_before: list[T0ArtifactFingerprint] | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    """Load frozen T0, refresh unique videos, write snapshot + meta."""
    manifest, t0_rows = load_t0_rows_from_manifest(manifest_path)
    t0_reference_at = parse_t0_reference_at(manifest)
    snapshot = snapshot_at or datetime.now(timezone.utc)
    elapsed_hours = calc_elapsed_hours(t0_reference_at, snapshot)

    cohort_rows, cohort_stats = build_unique_refresh_cohort(t0_rows)
    video_ids = [row["video_id"] for row in cohort_rows]

    details_by_id, batch_count, failed_ids = refresh_video_details(client, video_ids)
    records, refresh_counts = build_refresh_snapshot(
        cohort_rows,
        details_by_id=details_by_id,
        failed_ids=failed_ids,
        snapshot_at=snapshot,
        t0_reference_at=t0_reference_at,
    )

    invariants = verify_refresh_invariants(records, refresh_counts)

    t0_after = fingerprint_t0_artifacts(manifest, manifest_path)
    t0_before = t0_fingerprints_before or t0_after
    t0_modified = not t0_artifacts_unchanged(t0_before, t0_after)

    meta = {
        "schema_version": REFRESH_SCHEMA_VERSION,
        "t0_manifest_path": str(manifest_path.resolve()),
        "t0_reference_at": ensure_utc(t0_reference_at).isoformat(),
        "snapshot_at": ensure_utc(snapshot).isoformat(),
        "elapsed_hours_from_t0": elapsed_hours,
        "t0_rows": cohort_stats["t0_rows"],
        "unique_video_ids": cohort_stats["unique_video_ids"],
        "cross_keyword_duplicates_collapsed": cohort_stats["cross_keyword_duplicates_collapsed"],
        "refreshed": refresh_counts["refreshed"],
        "missing": refresh_counts["missing"],
        "failed": refresh_counts["failed"],
        "api_batch_count": batch_count,
        "invariants": invariants,
        "NO_DB_WRITES": True,
        "T0_ARTIFACTS_MODIFIED": t0_modified,
        "t0_artifact_fingerprints_before": [asdict(item) for item in t0_before],
        "t0_artifact_fingerprints_after": [asdict(item) for item in t0_after],
    }

    jsonl_path = export_refresh_snapshot(records, output_dir=output_dir, snapshot_at=snapshot)
    meta_path = export_refresh_meta(meta, output_dir=output_dir, snapshot_at=snapshot)
    meta["snapshot_path"] = str(jsonl_path)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "meta": meta,
        "jsonl_path": jsonl_path,
        "meta_path": meta_path,
        "records": records,
    }
    return jsonl_path, meta_path, summary
