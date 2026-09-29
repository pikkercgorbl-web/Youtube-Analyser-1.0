"""Offline analysis of exported RadarCandidate JSONL datasets (Stage 1.6)."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.radar_filter_metrics import (
    FILTER_SKIP_LANGUAGE,
    FILTER_SKIP_MIN_VIEWS,
    FILTER_SKIP_MIN_VIRAL_COEFF,
    FILTER_SKIP_PARSE_ERROR,
)

ANALYSIS_SCHEMA_VERSION = "1.6"
TOP_N_DEFAULT = 20

GROUP_PASSED = "passed"
GROUP_REJECTED_MIN_VIEWS = "rejected_min_views"
GROUP_REJECTED_MIN_VIRAL_COEFF = "rejected_min_viral_coeff"
GROUP_REJECTED_LANGUAGE = "rejected_language"
GROUP_PARSE_ERRORS = "parse_errors"
GROUP_ALL = "all"

SIGNAL_VIEWS = "views"
SIGNAL_VPH = "vph"
SIGNAL_VIDEO_AGE = "video_age_days"
SIGNAL_SUBSCRIBERS = "subscribers"
SIGNAL_VIRAL = "viral_coefficient"

TOP_CANDIDATE_FIELDS = (
    "keyword",
    "video_id",
    "channel_id",
    "video_title",
    "channel_title",
    "views",
    "subscribers",
    "vph",
    "viral_coefficient",
    "video_age_days",
    "qualification_state",
    "first_failure_reason",
)


def load_candidate_records(jsonl_path: Path) -> list[dict[str, Any]]:
    """Load candidate records from a Stage 1.5 JSONL export."""
    records: list[dict[str, Any]] = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        records.append(json.loads(stripped))
    return records


def _is_available(value: Any) -> bool:
    return value is not None


def _subscribers_meaningful(value: Any) -> bool:
    return value is not None and isinstance(value, (int, float)) and value > 0


def _percentile(sorted_values: list[float], percentile: float) -> float:
    if not sorted_values:
        raise ValueError("percentile requires at least one value")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * (percentile / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_values[int(rank)]
    lower_value = sorted_values[lower]
    upper_value = sorted_values[upper]
    return lower_value + (upper_value - lower_value) * (rank - lower)


def numeric_distribution(values: list[float]) -> dict[str, float | int]:
    sorted_values = sorted(values)
    return {
        "count": len(sorted_values),
        "min": sorted_values[0],
        "median": _percentile(sorted_values, 50),
        "p75": _percentile(sorted_values, 75),
        "p90": _percentile(sorted_values, 90),
        "p95": _percentile(sorted_values, 95),
        "max": sorted_values[-1],
    }


def _extract_numeric(records: list[dict[str, Any]], field: str) -> list[float]:
    values: list[float] = []
    for record in records:
        value = record.get(field)
        if _is_available(value):
            values.append(float(value))
    return values


def signal_availability(records: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    total = len(records)
    if total == 0:
        return {}

    views_count = len(_extract_numeric(records, SIGNAL_VIEWS))
    subscribers_present = sum(1 for record in records if _is_available(record.get(SIGNAL_SUBSCRIBERS)))
    subscribers_meaningful = sum(
        1 for record in records if _subscribers_meaningful(record.get(SIGNAL_SUBSCRIBERS))
    )
    vph_count = len(_extract_numeric(records, SIGNAL_VPH))
    age_count = len(_extract_numeric(records, SIGNAL_VIDEO_AGE))
    viral_count = len(_extract_numeric(records, SIGNAL_VIRAL))

    def _availability(count: int) -> dict[str, float | int]:
        return {
            "available_count": count,
            "availability_pct": round((count / total) * 100, 2) if total else 0.0,
        }

    return {
        SIGNAL_VIEWS: _availability(views_count),
        SIGNAL_SUBSCRIBERS: {
            "available_count": subscribers_present,
            "availability_pct": round((subscribers_present / total) * 100, 2),
            "meaningful_count": subscribers_meaningful,
            "meaningful_pct": round((subscribers_meaningful / total) * 100, 2),
        },
        SIGNAL_VPH: _availability(vph_count),
        SIGNAL_VIDEO_AGE: _availability(age_count),
        SIGNAL_VIRAL: _availability(viral_count),
    }


def _signal_stats_for_group(
    records: list[dict[str, Any]],
    field: str,
    *,
    include_availability: bool = False,
) -> dict[str, Any] | None:
    values = _extract_numeric(records, field)
    if not values:
        return None

    stats: dict[str, Any] = numeric_distribution(values)
    if include_availability and records:
        stats["available_count"] = len(values)
        stats["availability_pct"] = round((len(values) / len(records)) * 100, 2)
    return stats


def split_candidate_groups(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {
        GROUP_ALL: list(records),
        GROUP_PASSED: [],
        GROUP_REJECTED_MIN_VIEWS: [],
        GROUP_REJECTED_MIN_VIRAL_COEFF: [],
        GROUP_REJECTED_LANGUAGE: [],
        GROUP_PARSE_ERRORS: [],
    }

    for record in records:
        state = record.get("qualification_state")
        reason = record.get("first_failure_reason")
        if state == "passed":
            groups[GROUP_PASSED].append(record)
        elif state == "parse_error":
            groups[GROUP_PARSE_ERRORS].append(record)
        elif state == "rejected":
            if reason == FILTER_SKIP_MIN_VIEWS:
                groups[GROUP_REJECTED_MIN_VIEWS].append(record)
            elif reason == FILTER_SKIP_MIN_VIRAL_COEFF:
                groups[GROUP_REJECTED_MIN_VIRAL_COEFF].append(record)
            elif reason == FILTER_SKIP_LANGUAGE:
                groups[GROUP_REJECTED_LANGUAGE].append(record)

    return groups


def group_distribution(records: list[dict[str, Any]]) -> dict[str, Any]:
    distribution: dict[str, Any] = {"count": len(records)}

    views_stats = _signal_stats_for_group(records, SIGNAL_VIEWS)
    if views_stats:
        distribution[SIGNAL_VIEWS] = views_stats

    for field in (SIGNAL_VPH, SIGNAL_VIDEO_AGE, SIGNAL_SUBSCRIBERS, SIGNAL_VIRAL):
        stats = _signal_stats_for_group(records, field, include_availability=True)
        if stats:
            distribution[field] = stats

    return distribution


def _top_candidates(
    records: list[dict[str, Any]],
    *,
    sort_field: str,
    limit: int = TOP_N_DEFAULT,
    require_available: bool = True,
) -> list[dict[str, Any]]:
    filtered = records
    if require_available:
        filtered = [record for record in records if _is_available(record.get(sort_field))]

    sorted_records = sorted(
        filtered,
        key=lambda record: float(record[sort_field]),
        reverse=True,
    )
    return [
        {field: record.get(field) for field in TOP_CANDIDATE_FIELDS}
        for record in sorted_records[:limit]
    ]


def analyze_min_viral_coeff_group(records: list[dict[str, Any]]) -> dict[str, Any]:
    with_viral = [record for record in records if _is_available(record.get(SIGNAL_VIRAL))]
    without_viral = [record for record in records if not _is_available(record.get(SIGNAL_VIRAL))]
    with_subscribers = [
        record for record in records if _subscribers_meaningful(record.get(SIGNAL_SUBSCRIBERS))
    ]
    without_subscribers = [
        record for record in records if not _subscribers_meaningful(record.get(SIGNAL_SUBSCRIBERS))
    ]

    result: dict[str, Any] = {
        "total": len(records),
        "with_viral_coefficient": len(with_viral),
        "without_viral_coefficient": len(without_viral),
        "with_subscribers_gt_0": len(with_subscribers),
        "without_subscribers_gt_0": len(without_subscribers),
        "views_with_viral": group_distribution(with_viral).get(SIGNAL_VIEWS),
        "views_without_viral": group_distribution(without_viral).get(SIGNAL_VIEWS),
        "vph_with_viral": group_distribution(with_viral).get(SIGNAL_VPH),
        "vph_without_viral": group_distribution(without_viral).get(SIGNAL_VPH),
    }
    return result


def analyze_channel_size_examples(
    records: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    eligible: list[dict[str, Any]] = []
    for record in records:
        subscribers = record.get(SIGNAL_SUBSCRIBERS)
        views = record.get(SIGNAL_VIEWS)
        vph = record.get(SIGNAL_VPH)
        if not _subscribers_meaningful(subscribers):
            continue
        if not _is_available(views) or not _is_available(vph):
            continue
        enriched = {field: record.get(field) for field in TOP_CANDIDATE_FIELDS}
        enriched["views_per_subscriber"] = round(float(views) / float(subscribers), 4)
        enriched["vph_per_subscriber"] = round(float(vph) / float(subscribers), 4)
        eligible.append(enriched)

    by_vph = sorted(eligible, key=lambda item: float(item["vph"]), reverse=True)
    high_vph_large_subs = [
        item
        for item in by_vph
        if float(item["subscribers"]) >= 100_000
    ][:limit]
    high_vph_small_subs = [
        item
        for item in by_vph
        if float(item["subscribers"]) < 100_000
    ][:limit]

    return {
        "high_vph_large_subscribers": high_vph_large_subs,
        "high_vph_small_subscribers": high_vph_small_subs,
    }


def _dataset_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    groups = split_candidate_groups(records)
    keywords = sorted({str(record.get("keyword", "")) for record in records if record.get("keyword")})
    return {
        "keywords": keywords,
        "candidate_count": len(records),
        "passed": len(groups[GROUP_PASSED]),
        "rejected": sum(
            len(groups[name])
            for name in (
                GROUP_REJECTED_MIN_VIEWS,
                GROUP_REJECTED_MIN_VIRAL_COEFF,
                GROUP_REJECTED_LANGUAGE,
            )
        ),
        "parse_errors": len(groups[GROUP_PARSE_ERRORS]),
    }


def _format_stat(value: Any) -> str:
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}"
    return str(value)


def _observation_line(text: str) -> str:
    return f"- {text}"


def generate_initial_observations(analysis: dict[str, Any]) -> list[str]:
    """Build factual observations from computed statistics only."""
    observations: list[str] = []
    summary = analysis["dataset"]
    availability = analysis["signal_availability"]
    groups = analysis["groups"]

    observations.append(
        _observation_line(
            f"The dataset contains {summary['candidate_count']} candidates across "
            f"{', '.join(summary['keywords']) or 'unknown keywords'}.",
        ),
    )
    observations.append(
        _observation_line(
            f"Outcome counts: passed={summary['passed']}, rejected={summary['rejected']}, "
            f"parse_errors={summary['parse_errors']}.",
        ),
    )

    for signal, label in (
        (SIGNAL_VPH, "VPH"),
        (SIGNAL_VIRAL, "viral coefficient"),
        (SIGNAL_VIDEO_AGE, "video age"),
        (SIGNAL_SUBSCRIBERS, "subscribers field"),
    ):
        info = availability.get(signal, {})
        if not info:
            continue
        observations.append(
            _observation_line(
                f"{label} is available for {info.get('available_count', 0)} candidates "
                f"({info.get('availability_pct', 0)}%).",
            ),
        )
    subscribers_info = availability.get(SIGNAL_SUBSCRIBERS, {})
    if subscribers_info:
        observations.append(
            _observation_line(
                f"Subscribers > 0 appear in {subscribers_info.get('meaningful_count', 0)} candidates "
                f"({subscribers_info.get('meaningful_pct', 0)}%).",
            ),
        )

    for group_name, group_data in groups.items():
        if group_name == GROUP_ALL or group_data.get("count", 0) == 0:
            continue
        views = group_data.get(SIGNAL_VIEWS)
        vph = group_data.get(SIGNAL_VPH)
        if views:
            observations.append(
                _observation_line(
                    f"Group '{group_name}' (n={group_data['count']}): views median="
                    f"{_format_stat(views['median'])}, p90={_format_stat(views['p90'])}, "
                    f"max={_format_stat(views['max'])}.",
                ),
            )
        if vph:
            observations.append(
                _observation_line(
                    f"Group '{group_name}' (n={group_data['count']}): VPH median="
                    f"{_format_stat(vph['median'])}, p90={_format_stat(vph['p90'])}, "
                    f"max={_format_stat(vph['max'])}.",
                ),
            )

    min_viral = analysis.get("min_viral_coeff_analysis", {})
    if min_viral.get("total"):
        observations.append(
            _observation_line(
                f"Rejected by min_viral_coeff: {min_viral['with_viral_coefficient']} have viral "
                f"snapshot, {min_viral['without_viral_coefficient']} do not.",
            ),
        )
        observations.append(
            _observation_line(
                f"Among min_viral_coeff rejections, {min_viral['with_subscribers_gt_0']} have "
                f"subscribers > 0 in the dataset snapshot.",
            ),
        )

    observations.append(
        _observation_line(
            "VPH behaves as a potential velocity signal in this dataset and requires further "
            "validation across additional keyword datasets.",
        ),
    )
    return observations


def render_markdown_report(analysis: dict[str, Any]) -> str:
    summary = analysis["dataset"]
    lines = [
        "# Radar Candidate Analysis",
        "",
        "## Dataset",
        f"- keyword(s): {', '.join(summary['keywords']) or 'unknown'}",
        f"- candidate count: {summary['candidate_count']}",
        f"- passed: {summary['passed']}",
        f"- rejected: {summary['rejected']}",
        f"- parse errors: {summary['parse_errors']}",
        "",
        "## Group distribution",
        "",
        "| group | count |",
        "|---|---:|",
    ]

    for group_name, group_data in analysis["groups"].items():
        lines.append(f"| {group_name} | {group_data.get('count', 0)} |")

    lines.extend(["", "## Signal availability", ""])
    lines.append("| signal | available | availability % | meaningful | meaningful % |")
    lines.append("|---|---:|---:|---:|---:|")
    for signal, info in analysis["signal_availability"].items():
        lines.append(
            f"| {signal} | {info.get('available_count', 0)} | "
            f"{info.get('availability_pct', 0)} | "
            f"{info.get('meaningful_count', '-')} | "
            f"{info.get('meaningful_pct', '-')} |",
        )

    lines.extend(["", "## Signal distributions", ""])
    for group_name, group_data in analysis["groups"].items():
        if group_data.get("count", 0) == 0:
            continue
        lines.append(f"### {group_name}")
        lines.append("")
        for signal in (SIGNAL_VIEWS, SIGNAL_VPH, SIGNAL_VIDEO_AGE, SIGNAL_SUBSCRIBERS, SIGNAL_VIRAL):
            stats = group_data.get(signal)
            if not stats:
                continue
            header = (
                f"available={stats.get('available_count', stats.get('count'))}, "
                f"availability%={stats.get('availability_pct', '-')}"
                if signal != SIGNAL_VIEWS
                else f"count={stats.get('count')}"
            )
            lines.append(
                f"- **{signal}** ({header}): min={_format_stat(stats['min'])}, "
                f"median={_format_stat(stats['median'])}, p75={_format_stat(stats['p75'])}, "
                f"p90={_format_stat(stats['p90'])}, p95={_format_stat(stats['p95'])}, "
                f"max={_format_stat(stats['max'])}",
            )
        lines.append("")

    lines.extend(["## Rejected by min_viral_coeff", ""])
    min_viral = analysis["min_viral_coeff_analysis"]
    lines.extend(
        [
            f"- total: {min_viral.get('total', 0)}",
            f"- with viral coefficient snapshot: {min_viral.get('with_viral_coefficient', 0)}",
            f"- without viral coefficient snapshot: {min_viral.get('without_viral_coefficient', 0)}",
            f"- with subscribers > 0: {min_viral.get('with_subscribers_gt_0', 0)}",
            f"- without subscribers > 0: {min_viral.get('without_subscribers_gt_0', 0)}",
            "",
        ],
    )

    def _render_top_section(title: str, items: list[dict[str, Any]]) -> None:
        lines.extend([f"## {title}", ""])
        if not items:
            lines.append("_No records._")
            lines.append("")
            return
        lines.append(
            "| keyword | video_id | views | subscribers | vph | viral | age | state | reason | title |",
        )
        lines.append("|---|---|---:|---:|---:|---:|---:|---|---|---|")
        for item in items:
            title_text = str(item.get("video_title", "")).replace("|", "/")[:80]
            lines.append(
                f"| {item.get('keyword', '')} | {item.get('video_id', '')} | "
                f"{item.get('views', '')} | {item.get('subscribers', '')} | "
                f"{item.get('vph', '')} | {item.get('viral_coefficient', '')} | "
                f"{item.get('video_age_days', '')} | {item.get('qualification_state', '')} | "
                f"{item.get('first_failure_reason', '')} | {title_text} |",
            )
        lines.append("")

    tops = analysis["top_candidates"]
    _render_top_section("Top candidates by VPH", tops["by_vph"])
    _render_top_section("Top candidates by views", tops["by_views"])
    _render_top_section("Top candidates by viral coefficient", tops["by_viral_coefficient"])
    _render_top_section("Top rejected by VPH", tops["rejected_by_vph"])
    _render_top_section("Top rejected by views", tops["rejected_by_views"])

    lines.extend(["## High VPH vs channel size", ""])
    channel_size = analysis["channel_size_examples"]
    for section_name, heading in (
        ("high_vph_large_subscribers", "High VPH + large subscribers"),
        ("high_vph_small_subscribers", "High VPH + small subscribers"),
    ):
        lines.append(f"### {heading}")
        lines.append("")
        items = channel_size.get(section_name, [])
        if not items:
            lines.append("_No examples._")
        else:
            lines.append(
                "| views | subscribers | vph | views/subscribers | vph/subscribers | title |",
            )
            lines.append("|---:|---:|---:|---:|---:|---|")
            for item in items:
                title_text = str(item.get("video_title", "")).replace("|", "/")[:80]
                lines.append(
                    f"| {item.get('views', '')} | {item.get('subscribers', '')} | "
                    f"{item.get('vph', '')} | {item.get('views_per_subscriber', '')} | "
                    f"{item.get('vph_per_subscriber', '')} | {title_text} |",
                )
        lines.append("")

    lines.extend(["## Initial observations", ""])
    for observation in analysis.get("initial_observations", []):
        lines.append(observation)
    lines.append("")
    return "\n".join(lines)


def analyze_candidate_dataset(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze loaded candidate records and return a machine-readable report."""
    groups = split_candidate_groups(records)
    group_stats = {
        group_name: group_distribution(group_records)
        for group_name, group_records in groups.items()
        if group_records or group_name == GROUP_ALL
    }

    rejected_records = [
        record for record in records if record.get("qualification_state") == "rejected"
    ]

    analysis: dict[str, Any] = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": _dataset_summary(records),
        "signal_availability": signal_availability(records),
        "groups": group_stats,
        "min_viral_coeff_analysis": analyze_min_viral_coeff_group(
            groups[GROUP_REJECTED_MIN_VIRAL_COEFF],
        ),
        "top_candidates": {
            "by_vph": _top_candidates(records, sort_field=SIGNAL_VPH),
            "by_views": _top_candidates(records, sort_field=SIGNAL_VIEWS, require_available=False),
            "by_viral_coefficient": _top_candidates(records, sort_field=SIGNAL_VIRAL),
            "rejected_by_vph": _top_candidates(rejected_records, sort_field=SIGNAL_VPH),
            "rejected_by_views": _top_candidates(
                rejected_records,
                sort_field=SIGNAL_VIEWS,
                require_available=False,
            ),
        },
        "channel_size_examples": analyze_channel_size_examples(records),
    }
    analysis["initial_observations"] = generate_initial_observations(analysis)
    analysis["markdown_report"] = render_markdown_report(analysis)
    return analysis


def write_analysis_outputs(
    analysis: dict[str, Any],
    *,
    output_dir: Path,
    timestamp: datetime | None = None,
) -> tuple[Path, Path]:
    ts = timestamp or datetime.now(timezone.utc)
    stamp = ts.strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"radar_candidate_analysis_{stamp}.json"
    md_path = output_dir / f"radar_candidate_analysis_{stamp}.md"

    json_payload = {key: value for key, value in analysis.items() if key != "markdown_report"}
    json_path.write_text(
        json.dumps(json_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(analysis["markdown_report"], encoding="utf-8")
    return json_path, md_path
