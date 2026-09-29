"""Aggregation helpers for multi-keyword radar experiments (Stage 1.4)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

LOG_PREFIXES = (
    "[RADAR_INNERTUBE_METRICS]",
    "[RADAR_FILTER_METRICS]",
    "[RADAR_CANDIDATE_SUMMARY]",
    "[RADAR_CANDIDATE_DISTRIBUTION]",
)

PAGES_PATTERN = re.compile(r"страниц:\s*(\d+)")


@dataclass
class KeywordExperimentResult:
    keyword: str
    success: bool = True
    error: str | None = None
    pages: int | None = None
    innertube: dict[str, Any] = field(default_factory=dict)
    filter_metrics: dict[str, Any] = field(default_factory=dict)
    candidate_summary: dict[str, Any] = field(default_factory=dict)
    distribution: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "keyword": self.keyword,
            "success": self.success,
            "error": self.error,
            "pages": self.pages,
            "innertube": self.innertube,
            "filter_metrics": self.filter_metrics,
            "candidate_summary": self.candidate_summary,
            "distribution": self.distribution,
        }


def parse_json_log_line(line: str, prefix: str) -> dict[str, Any] | None:
    """Extract JSON payload from a structured radar log line."""
    if prefix not in line:
        return None
    brace_index = line.find("{", line.index(prefix))
    if brace_index < 0:
        return None
    try:
        payload = json.loads(line[brace_index:])
        if not isinstance(payload, dict):
            return None
        return payload
    except json.JSONDecodeError:
        return None


def parse_pages_from_log(text: str) -> int | None:
    """Parse page count from the final radar summary line when available."""
    matches = PAGES_PATTERN.findall(text)
    if not matches:
        return None
    return int(matches[-1])


def parse_keyword_scan_output(keyword: str, log_text: str) -> KeywordExperimentResult:
    """Build a keyword result from captured stdout during run_manual_scan."""
    result = KeywordExperimentResult(keyword=keyword)
    result.pages = parse_pages_from_log(log_text)

    for line in log_text.splitlines():
        innertube = parse_json_log_line(line, "[RADAR_INNERTUBE_METRICS]")
        if innertube is not None:
            result.innertube = innertube
            continue

        filter_metrics = parse_json_log_line(line, "[RADAR_FILTER_METRICS]")
        if filter_metrics is not None:
            result.filter_metrics = filter_metrics
            continue

        summary = parse_json_log_line(line, "[RADAR_CANDIDATE_SUMMARY]")
        if summary is not None:
            result.candidate_summary = summary
            continue

        distribution = parse_json_log_line(line, "[RADAR_CANDIDATE_DISTRIBUTION]")
        if distribution is not None:
            result.distribution = distribution

    return result


def _reason_count(result: KeywordExperimentResult, reason: str) -> int:
    reasons = result.filter_metrics.get("filter_skip_reasons") or {}
    if reason in reasons:
        return int(reasons[reason])
    distribution_reasons = result.distribution.get("filter_skip_reasons") or {}
    return int(distribution_reasons.get(reason, 0))


def _signal_available(result: KeywordExperimentResult, signal: str) -> int:
    availability = result.distribution.get("signal_availability") or {}
    if signal in availability:
        return int(availability[signal])
    summary_availability = result.candidate_summary.get("signal_availability") or {}
    return int(summary_availability.get(signal, 0))


def keyword_table_row(result: KeywordExperimentResult) -> dict[str, Any]:
    """Flatten one keyword result into a table row."""
    filter_metrics = result.filter_metrics
    summary = result.candidate_summary
    innertube = result.innertube

    discovered = int(filter_metrics.get("discovered_videos", 0))
    candidates = int(summary.get("candidate_count", discovered))
    passed = int(summary.get("passed_count", filter_metrics.get("passed_videos", 0)))
    rejected = int(summary.get("rejected_count", filter_metrics.get("filter_skips", 0)))

    return {
        "keyword": result.keyword,
        "success": result.success,
        "error": result.error,
        "pages": result.pages if result.pages is not None else innertube.get("request_count"),
        "request_count": int(innertube.get("request_count", 0)),
        "request_duration_ms": float(innertube.get("total_duration_ms", 0)),
        "request_errors": int(innertube.get("error_count", 0)),
        "discovered": discovered,
        "candidates": candidates,
        "passed": passed,
        "rejected": rejected,
        "parse_errors": int(filter_metrics.get("parse_errors", summary.get("parse_error_count", 0))),
        "min_views": _reason_count(result, "min_views"),
        "min_viral_coeff": _reason_count(result, "min_viral_coeff"),
        "language": _reason_count(result, "language"),
        "vph_available": _signal_available(result, "vph"),
        "viral_available": _signal_available(result, "viral_coefficient"),
        "distribution_groups": (result.distribution.get("groups") or {}),
    }


def aggregate_experiment_results(
    results: list[KeywordExperimentResult],
) -> dict[str, Any]:
    """Aggregate per-keyword experiment results into totals and reason counts."""
    rows = [keyword_table_row(result) for result in results]
    successful = [result for result in results if result.success]
    failed = [result for result in results if not result.success]

    rejection_totals: dict[str, int] = {}
    for result in successful:
        reasons = result.filter_metrics.get("filter_skip_reasons") or {}
        for reason, count in reasons.items():
            rejection_totals[reason] = rejection_totals.get(reason, 0) + int(count)

    totals = {
        "total_keywords": len(results),
        "successful_keywords": len(successful),
        "failed_keywords": len(failed),
        "total_discovered": sum(row["discovered"] for row in rows if row["success"]),
        "total_candidates": sum(row["candidates"] for row in rows if row["success"]),
        "total_passed": sum(row["passed"] for row in rows if row["success"]),
        "total_rejected": sum(row["rejected"] for row in rows if row["success"]),
        "total_parse_errors": sum(row["parse_errors"] for row in rows if row["success"]),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "keywords": [result.to_dict() for result in results],
        "table_rows": rows,
        "totals": totals,
        "rejection_reasons": dict(sorted(rejection_totals.items())),
        "failed_keyword_details": [
            {"keyword": result.keyword, "error": result.error}
            for result in failed
        ],
    }


def format_results_table(rows: list[dict[str, Any]]) -> str:
    """Render a fixed-width text table for experiment rows."""
    headers = (
        "keyword",
        "discovered",
        "candidates",
        "passed",
        "rejected",
        "min_views",
        "min_viral",
        "language",
        "vph_avail",
        "viral_avail",
    )

    def cell(row: dict[str, Any], key: str) -> str:
        if key == "keyword":
            return str(row.get("keyword", ""))
        if key == "min_viral":
            return str(row.get("min_viral_coeff", 0))
        if key == "vph_avail":
            return str(row.get("vph_available", 0))
        if key == "viral_avail":
            return str(row.get("viral_available", 0))
        return str(row.get(key, 0))

    string_rows = [{header: cell(row, header) for header in headers} for row in rows]
    widths = {
        header: max(len(header), *(len(r[header]) for r in string_rows), 0)
        for header in headers
    }

    def format_line(values: dict[str, str]) -> str:
        return "  ".join(values[header].ljust(widths[header]) for header in headers)

    lines = [format_line({h: h for h in headers}), format_line({h: "-" * widths[h] for h in headers})]
    for source_row, string_row in zip(rows, string_rows, strict=True):
        if not source_row.get("success", True):
            string_row["keyword"] = f"{string_row['keyword']} (FAILED)"
        lines.append(format_line(string_row))
    return "\n".join(lines)
