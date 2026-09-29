"""Multi-keyword candidate dataset collection helpers (Stage 1.7)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.services.radar_candidate import RadarCandidate
from app.services.radar_candidate_dataset import (
    count_candidate_states,
    export_candidates_jsonl,
    validate_dataset_invariants,
)

DEFAULT_KEYWORDS: tuple[str, ...] = (
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

EXPECTED_MIN_VIEWS = 10_000
EXPECTED_MIN_VIRAL_COEFF = 3.0
EXPECTED_UPLOAD_PERIOD = "all"


@dataclass
class ExperimentSettings:
    min_views: int
    min_viral_coeff: float
    upload_period: str
    register_channels: bool = False
    production_db_registration: bool = False

    def matches_expected(self) -> bool:
        return (
            self.min_views == EXPECTED_MIN_VIEWS
            and self.min_viral_coeff == EXPECTED_MIN_VIRAL_COEFF
            and self.upload_period == EXPECTED_UPLOAD_PERIOD
            and not self.register_channels
            and not self.production_db_registration
        )


@dataclass
class KeywordCollectionResult:
    keyword: str
    status: str
    candidates: list[RadarCandidate] = field(default_factory=list)
    jsonl_path: str | None = None
    meta_path: str | None = None
    duration_seconds: float = 0.0
    pages_scanned: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    counts: dict[str, int] = field(default_factory=dict)
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    signal_availability: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("candidates")
        return payload


def safe_keyword_slug(keyword: str) -> str:
    slug = keyword.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug, flags=re.UNICODE)
    slug = re.sub(r"[\s-]+", "_", slug)
    return slug[:80] or "keyword"


def build_keyword_output_paths(
    output_dir: Path,
    keyword: str,
    timestamp: datetime,
) -> tuple[Path, Path]:
    stamp = timestamp.strftime("%Y%m%d_%H%M%S")
    slug = safe_keyword_slug(keyword)
    jsonl_path = output_dir / f"radar_candidates_{stamp}_{slug}.jsonl"
    meta_path = output_dir / f"radar_candidates_{stamp}_{slug}_meta.json"
    return jsonl_path, meta_path


def count_rejection_reasons(candidates: list[RadarCandidate]) -> dict[str, int]:
    reasons: dict[str, int] = {}
    for candidate in candidates:
        if candidate.qualification_state != "rejected":
            continue
        reason = candidate.first_failure_reason
        if not reason:
            continue
        reasons[reason] = reasons.get(reason, 0) + 1
    return dict(sorted(reasons.items()))


def compute_basic_signal_availability(
    candidates: list[RadarCandidate],
) -> dict[str, Any]:
    total = len(candidates)
    if total == 0:
        return {
            "views": {"available_count": 0, "availability_pct": 0.0},
            "subscribers_field_present": {"available_count": 0, "availability_pct": 0.0},
            "subscribers_gt_zero": {"available_count": 0, "availability_pct": 0.0},
            "vph": {"available_count": 0, "availability_pct": 0.0},
            "video_age_days": {"available_count": 0, "availability_pct": 0.0},
            "viral_coefficient": {"available_count": 0, "availability_pct": 0.0},
        }

    views_count = sum(1 for candidate in candidates if candidate.views is not None)
    subs_present = sum(1 for candidate in candidates if candidate.subscribers is not None)
    subs_gt_zero = sum(
        1
        for candidate in candidates
        if candidate.subscribers is not None and candidate.subscribers > 0
    )
    vph_count = sum(1 for candidate in candidates if candidate.vph is not None)
    age_count = sum(1 for candidate in candidates if candidate.video_age_days is not None)
    viral_count = sum(1 for candidate in candidates if candidate.viral_coefficient is not None)

    def pct(count: int) -> float:
        return round((count / total) * 100, 2)

    return {
        "views": {"available_count": views_count, "availability_pct": pct(views_count)},
        "subscribers_field_present": {
            "available_count": subs_present,
            "availability_pct": pct(subs_present),
        },
        "subscribers_gt_zero": {
            "available_count": subs_gt_zero,
            "availability_pct": pct(subs_gt_zero),
        },
        "vph": {"available_count": vph_count, "availability_pct": pct(vph_count)},
        "video_age_days": {"available_count": age_count, "availability_pct": pct(age_count)},
        "viral_coefficient": {
            "available_count": viral_count,
            "availability_pct": pct(viral_count),
        },
    }


def check_candidate_invariant(counts: dict[str, int], total: int) -> bool:
    if counts.get("pending", 0):
        return False
    accounted = counts.get("passed", 0) + counts.get("rejected", 0) + counts.get("parse_errors", 0)
    return total == accounted


def build_counts_payload(candidates: list[RadarCandidate]) -> dict[str, int]:
    counts = count_candidate_states(candidates)
    counts["total"] = len(candidates)
    return counts


def finalize_keyword_success(
    *,
    keyword: str,
    candidates: list[RadarCandidate],
    output_dir: Path,
    settings: ExperimentSettings,
    source: str,
    duration_seconds: float,
    pages_scanned: int | None,
    timestamp: datetime | None = None,
) -> KeywordCollectionResult:
    counts = build_counts_payload(candidates)
    if not check_candidate_invariant(counts, len(candidates)):
        return KeywordCollectionResult(
            keyword=keyword,
            status="failed",
            candidates=candidates,
            duration_seconds=duration_seconds,
            pages_scanned=pages_scanned,
            error_type="InvariantError",
            error_message=(
                f"Candidate invariant failed: total={len(candidates)} != "
                f"passed+rejected+parse_errors="
                f"{counts.get('passed', 0) + counts.get('rejected', 0) + counts.get('parse_errors', 0)}"
            ),
            counts=counts,
        )

    try:
        jsonl_path, meta_path, _metadata = export_keyword_dataset(
            keyword=keyword,
            candidates=candidates,
            output_dir=output_dir,
            settings=settings,
            source=source,
            duration_seconds=duration_seconds,
            pages_scanned=pages_scanned,
            timestamp=timestamp,
        )
    except ValueError as exc:
        return KeywordCollectionResult(
            keyword=keyword,
            status="failed",
            candidates=candidates,
            duration_seconds=duration_seconds,
            pages_scanned=pages_scanned,
            error_type=type(exc).__name__,
            error_message=str(exc),
            counts=counts,
        )

    return KeywordCollectionResult(
        keyword=keyword,
        status="success",
        candidates=candidates,
        jsonl_path=str(jsonl_path),
        meta_path=str(meta_path),
        duration_seconds=duration_seconds,
        pages_scanned=pages_scanned,
        counts=counts,
        rejection_reasons=count_rejection_reasons(candidates),
        signal_availability=compute_basic_signal_availability(candidates),
    )


def finalize_keyword_failure(
    *,
    keyword: str,
    error_type: str,
    error_message: str,
    duration_seconds: float,
) -> KeywordCollectionResult:
    return KeywordCollectionResult(
        keyword=keyword,
        status="failed",
        duration_seconds=duration_seconds,
        error_type=error_type,
        error_message=error_message,
        counts={"total": 0, "passed": 0, "rejected": 0, "parse_errors": 0, "pending": 0},
    )


async def collect_keywords_sequential(
    keywords: list[str],
    *,
    scan_keyword: Callable[[str], Awaitable[Any]],
    output_dir: Path,
    settings: ExperimentSettings,
    source: str,
    on_keyword_start: Callable[[str, int, int], None] | None = None,
    on_keyword_done: Callable[[KeywordCollectionResult], None] | None = None,
) -> list[KeywordCollectionResult]:
    results: list[KeywordCollectionResult] = []
    total = len(keywords)
    for index, keyword in enumerate(keywords, start=1):
        if on_keyword_start:
            on_keyword_start(keyword, index, total)
        started = datetime.now(timezone.utc)
        try:
            scan_result = await scan_keyword(keyword)
            duration = (datetime.now(timezone.utc) - started).total_seconds()
            result = finalize_keyword_success(
                keyword=keyword,
                candidates=list(scan_result.candidates),
                output_dir=output_dir,
                settings=settings,
                source=source,
                duration_seconds=duration,
                pages_scanned=scan_result.pages_scanned,
                timestamp=started,
            )
        except Exception as exc:
            duration = (datetime.now(timezone.utc) - started).total_seconds()
            result = finalize_keyword_failure(
                keyword=keyword,
                error_type=type(exc).__name__,
                error_message=str(exc),
                duration_seconds=duration,
            )
        results.append(result)
        if on_keyword_done:
            on_keyword_done(result)
    return results


def write_collection_summary(
    summary: dict[str, Any],
    output_dir: Path,
    *,
    timestamp: datetime | None = None,
) -> tuple[Path, Path]:
    ts = timestamp or datetime.now(timezone.utc)
    stamp = ts.strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"radar_multi_keyword_dataset_{stamp}.json"
    md_path = output_dir / f"radar_multi_keyword_dataset_{stamp}.md"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_collection_markdown(summary), encoding="utf-8")
    return json_path, md_path


def export_keyword_dataset(
    *,
    keyword: str,
    candidates: list[RadarCandidate],
    output_dir: Path,
    settings: ExperimentSettings,
    source: str,
    duration_seconds: float,
    pages_scanned: int | None,
    timestamp: datetime | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    ts = timestamp or datetime.now(timezone.utc)
    jsonl_path, meta_path = build_keyword_output_paths(output_dir, keyword, ts)
    counts = count_candidate_states(candidates)

    validate_dataset_invariants(candidates)
    export_candidates_jsonl(candidates, jsonl_path)

    metadata: dict[str, Any] = {
        "keyword": keyword,
        "timestamp": ts.isoformat(),
        "min_views": settings.min_views,
        "min_viral_coeff": settings.min_viral_coeff,
        "upload_period": settings.upload_period,
        "register_channels": settings.register_channels,
        "production_db_registration": settings.production_db_registration,
        "total_candidates": len(candidates),
        "passed": counts["passed"],
        "rejected": counts["rejected"],
        "parse_errors": counts["parse_errors"],
        "source": source,
        "dataset_path": str(jsonl_path),
        "duration_seconds": round(duration_seconds, 2),
        "pages_scanned": pages_scanned,
        "schema_version": "1.7",
    }
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonl_path, meta_path, metadata


def aggregate_collection_summary(
    results: list[KeywordCollectionResult],
    *,
    settings: ExperimentSettings,
    explosive_channels_before: int,
    explosive_channels_after: int,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    successful = [result for result in results if result.status == "success"]
    failed = [result for result in results if result.status == "failed"]

    totals = {
        "total_candidates": sum(result.counts.get("total", 0) for result in successful),
        "total_passed": sum(result.counts.get("passed", 0) for result in successful),
        "total_rejected": sum(result.counts.get("rejected", 0) for result in successful),
        "total_parse_errors": sum(result.counts.get("parse_errors", 0) for result in successful),
    }

    aggregate_reasons: dict[str, int] = {}
    for result in successful:
        for reason, count in result.rejection_reasons.items():
            aggregate_reasons[reason] = aggregate_reasons.get(reason, 0) + count

    return {
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "experiment_settings": asdict(settings),
        "settings_match_expected": settings.matches_expected(),
        "keywords_requested": len(results),
        "keywords_successful": len(successful),
        "keywords_failed": len(failed),
        "explosive_channels_before": explosive_channels_before,
        "explosive_channels_after": explosive_channels_after,
        "production_db_registration_occurred": explosive_channels_after > explosive_channels_before,
        "results": [result.to_dict() for result in results],
        "totals": totals,
        "aggregate_rejection_reasons": dict(sorted(aggregate_reasons.items())),
    }


def render_collection_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Radar Multi-Keyword Dataset Collection",
        "",
        "## Experiment settings",
        f"- min_views: {summary['experiment_settings']['min_views']}",
        f"- min_viral_coeff: {summary['experiment_settings']['min_viral_coeff']}",
        f"- upload_period: {summary['experiment_settings']['upload_period']}",
        f"- register_channels: {summary['experiment_settings']['register_channels']}",
        f"- production_db_registration: {summary['experiment_settings']['production_db_registration']}",
        f"- settings_match_expected: {summary['settings_match_expected']}",
        "",
        "## Keyword results",
        "",
        "| Keyword | Status | Candidates | Passed | Rejected | Parse errors | Pages | Duration |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for result in summary["results"]:
        lines.append(
            f"| {result['keyword']} | {result['status']} | "
            f"{result['counts'].get('total', 0)} | {result['counts'].get('passed', 0)} | "
            f"{result['counts'].get('rejected', 0)} | {result['counts'].get('parse_errors', 0)} | "
            f"{result.get('pages_scanned', '')} | {result.get('duration_seconds', 0)} |",
        )

    totals = summary["totals"]
    lines.extend(
        [
            "",
            "## Aggregate totals",
            f"- total_candidates: {totals['total_candidates']}",
            f"- total_passed: {totals['total_passed']}",
            f"- total_rejected: {totals['total_rejected']}",
            f"- total_parse_errors: {totals['total_parse_errors']}",
            "",
            "## Rejection reasons per keyword",
            "",
            "| Keyword | min_views | min_viral_coeff | language | other |",
            "|---|---:|---:|---:|---:|",
        ],
    )

    for result in summary["results"]:
        if result["status"] != "success":
            lines.append(f"| {result['keyword']} | - | - | - | failed |")
            continue
        reasons = result.get("rejection_reasons", {})
        other = sum(
            count
            for reason, count in reasons.items()
            if reason not in {"min_views", "min_viral_coeff", "language"}
        )
        lines.append(
            f"| {result['keyword']} | {reasons.get('min_views', 0)} | "
            f"{reasons.get('min_viral_coeff', 0)} | {reasons.get('language', 0)} | {other} |",
        )

    lines.extend(
        [
            "",
            "## Signal availability",
            "",
            "| Keyword | Candidates | VPH % | Viral % | Subs>0 % | Age % |",
            "|---|---:|---:|---:|---:|---:|",
        ],
    )
    for result in summary["results"]:
        if result["status"] != "success":
            continue
        availability = result.get("signal_availability", {})
        lines.append(
            f"| {result['keyword']} | {result['counts'].get('total', 0)} | "
            f"{availability.get('vph', {}).get('availability_pct', 0)} | "
            f"{availability.get('viral_coefficient', {}).get('availability_pct', 0)} | "
            f"{availability.get('subscribers_gt_zero', {}).get('availability_pct', 0)} | "
            f"{availability.get('video_age_days', {}).get('availability_pct', 0)} |",
        )

    lines.extend(
        [
            "",
            "## Subscriber availability",
            "",
            "| Keyword | Subs field % | Subs>0 % |",
            "|---|---:|---:|",
        ],
    )
    for result in summary["results"]:
        if result["status"] != "success":
            continue
        availability = result.get("signal_availability", {})
        lines.append(
            f"| {result['keyword']} | "
            f"{availability.get('subscribers_field_present', {}).get('availability_pct', 0)} | "
            f"{availability.get('subscribers_gt_zero', {}).get('availability_pct', 0)} |",
        )

    lines.extend(
        [
            "",
            "## DB registration check",
            f"- explosive_channels before: {summary['explosive_channels_before']}",
            f"- explosive_channels after: {summary['explosive_channels_after']}",
            f"- production_db_registration_occurred: {summary['production_db_registration_occurred']}",
            "",
        ],
    )

    if summary["keywords_failed"]:
        lines.append("## Failed keywords")
        lines.append("")
        for result in summary["results"]:
            if result["status"] != "failed":
                continue
            lines.append(
                f"- {result['keyword']}: {result.get('error_type')} — {result.get('error_message')}",
            )
        lines.append("")

    return "\n".join(lines)
