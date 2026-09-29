"""Multi-keyword validation T0 cohort collection (Stage 1.9A)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.services.explosive_channels_radar_worker import (
    AnalysisScanResult,
    ExplosiveChannelsRadarWorker,
)
from app.services.radar_candidate import RadarCandidate
from app.services.radar_candidate_enrichment import VideoDetailsClient
from app.services.radar_validation_scan import run_validation_analysis_scan
from app.services.radar_validation_t0_dataset import (
    _sanitize_keyword_for_filename,
    count_excluded_after_enrichment,
    persist_keyword_t0_outputs,
    split_raw_and_regular,
)

VALIDATION_COHORT_KEYWORDS: tuple[str, ...] = (
    "AI tools",
    "productivity",
    "fitness",
    "gaming",
    "history",
    "technology",
    "self improvement",
    "interesting facts",
    "home improvement",
    "travel",
)

COHORT_SOURCE = "run_radar_validation_cohort.py"


@dataclass
class KeywordCohortResult:
    keyword: str
    status: str
    jsonl_path: str | None = None
    meta_path: str | None = None
    duration_seconds: float = 0.0
    raw_candidates: int = 0
    regular_candidates: int = 0
    excluded_after_enrichment: int = 0
    passed: int = 0
    rejected: int = 0
    parse_errors: int = 0
    format_violations: int = 0
    regular_format_violations: int = 0
    enrichment_summary: dict[str, Any] = field(default_factory=dict)
    invariant_ok: bool = False
    error_type: str | None = None
    error_message: str | None = None

    def to_manifest_entry(self) -> dict[str, Any]:
        return {
            "keyword": self.keyword,
            "status": self.status,
            "dataset_path": self.jsonl_path,
            "meta_path": self.meta_path,
            "duration_seconds": round(self.duration_seconds, 2),
            "raw_candidates": self.raw_candidates,
            "regular_candidates": self.regular_candidates,
            "excluded_after_enrichment": self.excluded_after_enrichment,
            "candidate_count": self.raw_candidates,
            "passed": self.passed,
            "rejected": self.rejected,
            "parse_errors": self.parse_errors,
            "format_violations": self.format_violations,
            "regular_format_violations": self.regular_format_violations,
            "enrichment_summary": self.enrichment_summary,
            "invariant_ok": self.invariant_ok,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


def determine_keyword_status(
    *,
    error_type: str | None,
    invariant_ok: bool,
    excluded_after_enrichment: int,
    enrichment_failed: int,
) -> str:
    if error_type:
        return "FAILED"
    if not invariant_ok:
        return "FAILED"
    if excluded_after_enrichment > 0 or enrichment_failed > 0:
        return "PARTIAL"
    return "SUCCESS"


def build_cohort_manifest(
    *,
    keywords: list[str],
    results: list[KeywordCohortResult],
    cohort_timestamp: datetime,
    total_duration_seconds: float,
    explosive_channels_before: int,
    explosive_channels_after: int,
) -> dict[str, Any]:
    stamp = cohort_timestamp.strftime("%Y%m%d_%H%M%S")
    per_keyword = [result.to_manifest_entry() for result in results]

    total_raw = sum(result.raw_candidates for result in results)
    total_regular = sum(result.regular_candidates for result in results)
    total_passed = sum(result.passed for result in results)
    total_rejected = sum(result.rejected for result in results)
    total_parse_errors = sum(result.parse_errors for result in results)
    total_format_excluded = sum(result.excluded_after_enrichment for result in results)
    total_format_violations = sum(result.format_violations for result in results)

    enrichment_totals = aggregate_enrichment_from_results(results)

    keywords_successful = sum(1 for result in results if result.status == "SUCCESS")
    keywords_partial = sum(1 for result in results if result.status == "PARTIAL")
    keywords_failed = sum(1 for result in results if result.status == "FAILED")

    return {
        "timestamp": cohort_timestamp.isoformat(),
        "cohort_run_id": stamp,
        "schema_version": "1.9A",
        "source": COHORT_SOURCE,
        "keywords": keywords,
        "explosive_channels_before": explosive_channels_before,
        "explosive_channels_after": explosive_channels_after,
        "production_db_registration_occurred": explosive_channels_before != explosive_channels_after,
        "total_duration_seconds": round(total_duration_seconds, 2),
        "keywords_successful": keywords_successful,
        "keywords_partial": keywords_partial,
        "keywords_failed": keywords_failed,
        "totals": {
            "raw_candidates": total_raw,
            "regular_candidates": total_regular,
            "passed": total_passed,
            "rejected": total_rejected,
            "parse_errors": total_parse_errors,
            "format_exclusions": total_format_excluded,
            "format_violations": total_format_violations,
            "enrichment_summary": enrichment_totals,
        },
        "per_keyword": per_keyword,
        "dataset_paths": [result.jsonl_path for result in results if result.jsonl_path],
        "invariant_status": all(result.invariant_ok for result in results if result.status != "FAILED"),
    }


def build_global_summary_payload(
    manifest: dict[str, Any],
    manifest_path: Path,
) -> dict[str, Any]:
    totals = manifest["totals"]
    enrichment = totals["enrichment_summary"]
    return {
        "total_raw_candidates": totals["raw_candidates"],
        "total_regular_candidates": totals["regular_candidates"],
        "total_passed": totals["passed"],
        "total_rejected": totals["rejected"],
        "total_parse_errors": totals["parse_errors"],
        "total_format_exclusions": totals["format_exclusions"],
        "total_format_violations": totals["format_violations"],
        "total_enrichment_failures": enrichment.get("enrichment_failed", 0),
        "keywords_successful": manifest["keywords_successful"],
        "keywords_partial": manifest["keywords_partial"],
        "keywords_failed": manifest["keywords_failed"],
        "total_duration_seconds": manifest["total_duration_seconds"],
        "dataset_paths": manifest["dataset_paths"],
        "manifest_path": str(manifest_path),
        "per_keyword_table": [
            {
                "keyword": entry["keyword"],
                "status": entry["status"],
                "raw": entry["raw_candidates"],
                "regular": entry["regular_candidates"],
                "passed": entry["passed"],
                "rejected": entry["rejected"],
                "format_excluded": entry["excluded_after_enrichment"],
                "enrichment_ok": entry.get("enrichment_summary", {}).get("enrichment_ok", 0),
                "enrichment_partial": entry.get("enrichment_summary", {}).get("enrichment_partial", 0),
                "enrichment_failed": entry.get("enrichment_summary", {}).get("enrichment_failed", 0),
                "VPH_available": entry.get("enrichment_summary", {}).get("vph_available", 0),
                "V/S_available": entry.get("enrichment_summary", {}).get("views_per_subscriber_available", 0),
            }
            for entry in manifest["per_keyword"]
        ],
    }


def write_cohort_manifest(
    manifest: dict[str, Any],
    *,
    output_dir: Path,
    cohort_timestamp: datetime,
) -> Path:
    stamp = cohort_timestamp.strftime("%Y%m%d_%H%M%S")
    manifest_path = output_dir / f"cohort_T0_{stamp}_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest_path


def finalize_keyword_cohort_success(
    *,
    keyword: str,
    candidates: list[RadarCandidate],
    output_dir: Path,
    duration_seconds: float,
    missing_video_count: int,
    cohort_timestamp: datetime,
) -> KeywordCohortResult:
    jsonl_path, meta_path, meta_payload, enrichment_summary, dataset_summary = persist_keyword_t0_outputs(
        candidates,
        keyword=keyword,
        output_dir=output_dir,
        source=COHORT_SOURCE,
        duration_seconds=duration_seconds,
        missing_video_count=missing_video_count,
        timestamp=cohort_timestamp,
    )

    _, regular_candidates = split_raw_and_regular(candidates)
    excluded = count_excluded_after_enrichment(candidates)
    enrichment_failed = enrichment_summary.get("enrichment_failed", 0)
    invariant_ok = dataset_summary["invariant_ok"]

    status = determine_keyword_status(
        error_type=None,
        invariant_ok=invariant_ok,
        excluded_after_enrichment=excluded,
        enrichment_failed=enrichment_failed,
    )

    return KeywordCohortResult(
        keyword=keyword,
        status=status,
        jsonl_path=str(jsonl_path),
        meta_path=str(meta_path),
        duration_seconds=duration_seconds,
        raw_candidates=len(candidates),
        regular_candidates=len(regular_candidates),
        excluded_after_enrichment=excluded,
        passed=dataset_summary["passed"],
        rejected=dataset_summary["rejected"],
        parse_errors=dataset_summary["parse_errors"],
        format_violations=dataset_summary["format_violations"],
        regular_format_violations=meta_payload["regular_format_violations"],
        enrichment_summary=enrichment_summary,
        invariant_ok=invariant_ok,
    )


def finalize_keyword_cohort_failure(
    *,
    keyword: str,
    error_type: str,
    error_message: str,
    duration_seconds: float,
) -> KeywordCohortResult:
    return KeywordCohortResult(
        keyword=keyword,
        status="FAILED",
        duration_seconds=duration_seconds,
        error_type=error_type,
        error_message=error_message,
        invariant_ok=False,
    )


async def collect_validation_cohort(
    keywords: list[str],
    *,
    worker: ExplosiveChannelsRadarWorker,
    youtube_client: VideoDetailsClient | None,
    output_dir: Path,
    cohort_timestamp: datetime | None = None,
    scan_keyword: Callable[
        [ExplosiveChannelsRadarWorker, str, VideoDetailsClient | None],
        Awaitable[tuple[AnalysisScanResult, dict[str, int]]],
    ] | None = None,
    on_keyword_start: Callable[[str, int, int], None] | None = None,
    on_keyword_done: Callable[[KeywordCohortResult], None] | None = None,
) -> list[KeywordCohortResult]:
    """Collect fresh T0 datasets for each keyword sequentially."""
    scan_fn = scan_keyword or (
        lambda w, kw, client: run_validation_analysis_scan(w, kw, youtube_client=client)
    )
    ts = cohort_timestamp or datetime.now(timezone.utc)
    results: list[KeywordCohortResult] = []
    total = len(keywords)

    for index, keyword in enumerate(keywords, start=1):
        if on_keyword_start:
            on_keyword_start(keyword, index, total)

        started = datetime.now(timezone.utc)
        try:
            scan_result, enrichment_meta = await scan_fn(worker, keyword, youtube_client)
            duration = (datetime.now(timezone.utc) - started).total_seconds()
            result = finalize_keyword_cohort_success(
                keyword=keyword,
                candidates=scan_result.candidates,
                output_dir=output_dir,
                duration_seconds=duration,
                missing_video_count=enrichment_meta.get("missing_video_count", 0),
                cohort_timestamp=ts,
            )
        except Exception as exc:
            duration = (datetime.now(timezone.utc) - started).total_seconds()
            result = finalize_keyword_cohort_failure(
                keyword=keyword,
                error_type=type(exc).__name__,
                error_message=str(exc),
                duration_seconds=duration,
            )

        results.append(result)
        if on_keyword_done:
            on_keyword_done(result)

    return results


def aggregate_enrichment_from_results(results: list[KeywordCohortResult]) -> dict[str, Any]:
    """Sum enrichment counters across keyword results for manifest totals."""
    totals = {
        "candidates_total": 0,
        "enrichment_ok": 0,
        "enrichment_partial": 0,
        "enrichment_failed": 0,
        "missing_video": 0,
        "published_at_available": 0,
        "duration_available": 0,
        "age_hours_available": 0,
        "vph_available": 0,
        "final_subscribers_available": 0,
        "views_per_subscriber_available": 0,
        "regular_count": 0,
        "short_count": 0,
        "live_count": 0,
        "unknown_count": 0,
    }
    for result in results:
        if result.status == "FAILED":
            continue
        summary = result.enrichment_summary
        for key in totals:
            totals[key] += int(summary.get(key, 0))
    return totals


def build_cohort_manifest_with_aggregates(
    *,
    keywords: list[str],
    results: list[KeywordCohortResult],
    cohort_timestamp: datetime,
    total_duration_seconds: float,
    explosive_channels_before: int,
    explosive_channels_after: int,
) -> dict[str, Any]:
    manifest = build_cohort_manifest(
        keywords=keywords,
        results=results,
        cohort_timestamp=cohort_timestamp,
        total_duration_seconds=total_duration_seconds,
        explosive_channels_before=explosive_channels_before,
        explosive_channels_after=explosive_channels_after,
    )
    manifest["totals"]["enrichment_summary"] = aggregate_enrichment_from_results(results)
    return manifest


def keyword_output_slug(keyword: str) -> str:
    return _sanitize_keyword_for_filename(keyword)
