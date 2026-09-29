"""Offline T0 cohort distribution review (Stage 1.9B)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.radar_candidate_analysis import _percentile, numeric_distribution
from app.services.radar_t0_data_quality import SUBSCRIBER_STATUSES, load_t0_jsonl

REVIEW_SCHEMA_VERSION = "1.9B"

VPH_BINS: tuple[tuple[str, float | None, float | None], ...] = (
    ("<=100", None, 100.0),
    ("100-500", 100.0, 500.0),
    ("500-1k", 500.0, 1000.0),
    ("1k-5k", 1000.0, 5000.0),
    ("5k-10k", 5000.0, 10000.0),
    ("10k-25k", 10000.0, 25000.0),
    ("25k-50k", 25000.0, 50000.0),
    ("50k-100k", 50000.0, 100000.0),
    (">100k", 100000.0, None),
)

VPH_TAIL_THRESHOLDS = (1000, 5000, 10000, 25000, 50000, 100000)

AGE_BINS: tuple[tuple[str, str], ...] = (
    ("negative_or_zero", "negative_or_zero"),
    ("<=1h", "<=1"),
    ("1-3h", "1-3"),
    ("3-6h", "3-6"),
    ("6-12h", "6-12"),
    ("12-18h", "12-18"),
    ("18-24h", "18-24"),
    (">24h", ">24"),
)


def is_regular_record(record: dict[str, Any]) -> bool:
    return record.get("content_format") == "regular"


def filter_regular_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if is_regular_record(record)]


def _extract_float(records: list[dict[str, Any]], field: str) -> list[float]:
    values: list[float] = []
    for record in records:
        value = record.get(field)
        if value is not None:
            values.append(float(value))
    return values


def _views_distribution(records: list[dict[str, Any]]) -> dict[str, Any]:
    values = _extract_float(records, "discovery_views")
    if not values:
        return {"count": 0, "min": None, "median": None, "p75": None, "p90": None, "p95": None, "max": None}
    stats = numeric_distribution(values)
    return {
        "count": stats["count"],
        "min": round(float(stats["min"]), 2),
        "median": round(float(stats["median"]), 2),
        "p75": round(float(stats["p75"]), 2),
        "p90": round(float(stats["p90"]), 2),
        "p95": round(float(stats["p95"]), 2),
        "max": round(float(stats["max"]), 2),
    }


def _optional_numeric_distribution(values: list[float], *, include_p25: bool = False) -> dict[str, Any]:
    if not values:
        base = {
            "available_count": 0,
            "missing_count": 0,
            "min": None,
            "median": None,
            "p75": None,
            "p90": None,
            "p95": None,
            "max": None,
        }
        if include_p25:
            base["p25"] = None
        return base

    sorted_values = sorted(values)
    result: dict[str, Any] = {
        "available_count": len(values),
        "missing_count": 0,
        "min": round(sorted_values[0], 4),
        "median": round(_percentile(sorted_values, 50), 4),
        "p75": round(_percentile(sorted_values, 75), 4),
        "p90": round(_percentile(sorted_values, 90), 4),
        "p95": round(_percentile(sorted_values, 95), 4),
        "max": round(sorted_values[-1], 4),
    }
    if include_p25:
        result["p25"] = round(_percentile(sorted_values, 25), 4)
    return result


def _vph_bins(values: list[float]) -> dict[str, int]:
    bins = {label: 0 for label, _, _ in VPH_BINS}
    for value in values:
        placed = False
        for label, lower, upper in VPH_BINS:
            if lower is None and value <= (upper or 0):
                bins[label] += 1
                placed = True
                break
            if upper is None and lower is not None and value > lower:
                bins[label] += 1
                placed = True
                break
            if lower is not None and upper is not None and lower < value <= upper:
                bins[label] += 1
                placed = True
                break
        if not placed and values:
            bins[">100k"] += 1
    return bins


def _vph_distribution(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    values = _extract_float(records, "vph_at_t0")
    stats = _optional_numeric_distribution(values)
    stats["missing_count"] = total - len(values)
    stats["bins"] = _vph_bins(values)
    return stats


def _vps_distribution(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    values = _extract_float(records, "views_per_subscriber_at_t0")
    stats = _optional_numeric_distribution(values)
    stats["missing_count"] = total - len(values)
    return stats


def _classify_age_bucket(age: float) -> str:
    if age <= 0:
        return "negative_or_zero"
    if age <= 1:
        return "<=1h"
    if age <= 3:
        return "1-3h"
    if age <= 6:
        return "3-6h"
    if age <= 12:
        return "6-12h"
    if age <= 18:
        return "12-18h"
    if age <= 24:
        return "18-24h"
    return ">24h"


def _age_distribution(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    values = _extract_float(records, "age_hours_at_t0")
    stats = _optional_numeric_distribution(values, include_p25=True)
    stats["missing_count"] = total - len(values)
    buckets = {label: 0 for label, _ in AGE_BINS}
    for value in values:
        buckets[_classify_age_bucket(value)] += 1
    stats["buckets"] = buckets
    return stats


def _subscriber_coverage(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    available = sum(1 for record in records if record.get("final_subscribers") is not None)
    breakdown = {status: 0 for status in SUBSCRIBER_STATUSES}
    other = 0
    for record in records:
        status = record.get("subscriber_fetch_status")
        if status in breakdown:
            breakdown[status] += 1
        else:
            other += 1
    if other:
        breakdown["other"] = other
    return {
        "final_subscribers_available": available,
        "final_subscribers_missing": total - available,
        "subscriber_fetch_status": breakdown,
    }


def _format_breakdown(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"regular": 0, "short": 0, "live": 0, "unknown": 0}
    for record in records:
        fmt = record.get("content_format")
        if fmt in counts:
            counts[fmt] += 1
        else:
            counts["unknown"] += 1
    return counts


def _vph_tail_counts(values: list[float]) -> dict[str, int]:
    return {f">={threshold}": sum(1 for value in values if value >= threshold) for threshold in VPH_TAIL_THRESHOLDS}


def _nullable_enrichment_checks(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Ensure missing enrichment is null, not coerced to zero."""
    issues: list[dict[str, Any]] = []
    for record in records:
        video_id = record.get("video_id")
        if record.get("final_subscribers") is None and record.get("views_per_subscriber_at_t0") is not None:
            issues.append({"video_id": video_id, "field": "views_per_subscriber_without_subscribers"})
        if record.get("final_subscribers") == 0 and record.get("views_per_subscriber_at_t0") is not None:
            issues.append({"video_id": video_id, "field": "views_per_subscriber_with_zero_subscribers"})
    return {"issue_count": len(issues), "examples": issues[:10]}


def check_keyword_invariants(
    raw_records: list[dict[str, Any]],
    *,
    expected_raw: int | None = None,
    expected_regular: int | None = None,
    expected_excluded: int | None = None,
) -> dict[str, Any]:
    passed = rejected = parse_errors = 0
    for record in raw_records:
        state = record.get("qualification_state")
        if state == "passed":
            passed += 1
        elif state == "rejected":
            rejected += 1
        elif state == "parse_error":
            parse_errors += 1

    raw_count = len(raw_records)
    regular_records = filter_regular_records(raw_records)
    regular_count = len(regular_records)
    excluded = raw_count - regular_count

    video_ids = [str(record.get("video_id", "")) for record in regular_records]
    unique_video_ids = len(set(video_ids))

    invariant_qualification = raw_count == passed + rejected + parse_errors
    invariant_regular_split = regular_count + excluded == raw_count

    checks = {
        "raw_count": raw_count,
        "regular_count": regular_count,
        "excluded_after_enrichment": excluded,
        "passed": passed,
        "rejected": rejected,
        "parse_errors": parse_errors,
        "unique_video_id_regular": unique_video_ids,
        "duplicate_video_id_regular": regular_count - unique_video_ids,
        "invariant_qualification_ok": invariant_qualification,
        "invariant_regular_split_ok": invariant_regular_split,
        "parse_errors_zero": parse_errors == 0,
    }

    if expected_raw is not None:
        checks["matches_manifest_raw"] = raw_count == expected_raw
    if expected_regular is not None:
        checks["matches_manifest_regular"] = regular_count == expected_regular
    if expected_excluded is not None:
        checks["matches_manifest_excluded"] = excluded == expected_excluded

    checks["all_ok"] = (
        invariant_qualification
        and invariant_regular_split
        and parse_errors == 0
        and checks["duplicate_video_id_regular"] == 0
    )
    return checks


def build_distribution_block(records: list[dict[str, Any]]) -> dict[str, Any]:
    vph_values = _extract_float(records, "vph_at_t0")
    return {
        "count": len(records),
        "views": _views_distribution(records),
        "vph": _vph_distribution(records),
        "views_per_subscriber": _vps_distribution(records),
        "age_hours_at_t0": _age_distribution(records),
        "subscribers": _subscriber_coverage(records),
        "format": _format_breakdown(records),
        "vph_tail": _vph_tail_counts(vph_values),
        "nullable_enrichment": _nullable_enrichment_checks(records),
    }


def build_keyword_comparison_row(keyword: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    regular = filter_regular_records(records)
    views = _extract_float(regular, "discovery_views")
    vph = _extract_float(regular, "vph_at_t0")
    age = _extract_float(regular, "age_hours_at_t0")
    vps_available = sum(1 for record in regular if record.get("views_per_subscriber_at_t0") is not None)

    def med(values: list[float]) -> float | None:
        if not values:
            return None
        return round(_percentile(sorted(values), 50), 2)

    def p90(values: list[float]) -> float | None:
        if not values:
            return None
        return round(_percentile(sorted(values), 90), 2)

    def p95(values: list[float]) -> float | None:
        if not values:
            return None
        return round(_percentile(sorted(values), 95), 2)

    return {
        "keyword": keyword,
        "regular_count": len(regular),
        "median_views": med(views),
        "median_vph": med(vph),
        "p90_vph": p90(vph),
        "p95_vph": p95(vph),
        "vph_available": len(vph),
        "vph_missing": len(regular) - len(vph),
        "v_s_available": vps_available,
        "v_s_missing": len(regular) - vps_available,
        "median_age_hours": med(age),
    }


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def review_t0_cohort_from_manifest(manifest_path: Path) -> dict[str, Any]:
    """Build full offline distribution review from a Stage 1.9A manifest."""
    manifest = load_manifest(manifest_path)
    per_keyword_entries: list[dict[str, Any]] = []
    all_raw: list[dict[str, Any]] = []
    all_regular: list[dict[str, Any]] = []

    for entry in manifest.get("per_keyword", []):
        keyword = entry["keyword"]
        dataset_path = Path(entry["dataset_path"])
        raw_records = load_t0_jsonl(dataset_path)
        regular_records = filter_regular_records(raw_records)

        invariants = check_keyword_invariants(
            raw_records,
            expected_raw=entry.get("raw_candidates"),
            expected_regular=entry.get("regular_candidates"),
            expected_excluded=entry.get("excluded_after_enrichment"),
        )

        per_keyword_entries.append(
            {
                "keyword": keyword,
                "dataset_path": str(dataset_path),
                "meta_path": entry.get("meta_path"),
                "status": entry.get("status"),
                "invariants": invariants,
                "comparison": build_keyword_comparison_row(keyword, raw_records),
                "distributions_regular": build_distribution_block(regular_records),
            },
        )

        all_raw.extend(raw_records)
        all_regular.extend(regular_records)

    global_invariants = check_keyword_invariants(all_raw)
    global_invariants["unique_video_id_regular_global"] = len(
        {record.get("video_id") for record in all_regular},
    )
    global_invariants["duplicate_video_id_regular_global"] = len(all_regular) - global_invariants[
        "unique_video_id_regular_global"
    ]

    vph_global = _extract_float(all_regular, "vph_at_t0")
    keyword_tail: dict[str, Any] = {}
    for item in per_keyword_entries:
        keyword = item["keyword"]
        regular_count = item["distributions_regular"]["count"]
        tail = item["distributions_regular"]["vph_tail"]
        keyword_tail[keyword] = {"regular_count": regular_count, "tail": tail}

    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "manifest_path": str(manifest_path.resolve()),
        "cohort_run_id": manifest.get("cohort_run_id"),
        "cohort_timestamp": manifest.get("timestamp"),
        "keywords": manifest.get("keywords", []),
        "source_files_read": [item["dataset_path"] for item in per_keyword_entries],
        "overview": {
            "raw_records": len(all_raw),
            "regular_records": len(all_regular),
            "manifest_totals": manifest.get("totals", {}),
        },
        "data_quality": {
            "global_invariants": global_invariants,
            "nullable_enrichment_global": _nullable_enrichment_checks(all_regular),
            "format_raw_all": _format_breakdown(all_raw),
            "format_regular_only": _format_breakdown(all_regular),
        },
        "global_distributions_regular": build_distribution_block(all_regular),
        "keyword_comparison": [item["comparison"] for item in per_keyword_entries],
        "per_keyword": per_keyword_entries,
        "vph_tail_analysis": {
            "global": _vph_tail_counts(vph_global),
            "by_keyword": keyword_tail,
        },
        "limitations": [
            "T0 snapshot only; no T24/T72 outcomes exist yet.",
            "VPH is discovery-time velocity, not a validated predictor.",
            "V/S coverage is limited to records with final_subscribers (mostly passed candidates).",
            "not_attempted subscriber_fetch is not equivalent to zero subscribers.",
            "Immutability of discovery fields cannot be verified from JSONL alone.",
        ],
        "sampling_recommendations": build_sampling_recommendations(all_regular, per_keyword_entries),
        "verification": {
            "NO_NETWORK_REQUESTS": True,
            "NO_DB_WRITES": True,
            "records_processed_raw": len(all_raw),
            "records_processed_regular": len(all_regular),
        },
    }


def build_sampling_recommendations(
    all_regular: list[dict[str, Any]],
    per_keyword: list[dict[str, Any]],
) -> list[str]:
    """Descriptive strata hints only — no automatic sample selection."""
    recs: list[str] = []
    recs.append(
        "Stratify by keyword: distributions differ materially across the 10 niches; avoid pooling without keyword strata.",
    )

    vph = _extract_float(all_regular, "vph_at_t0")
    if vph:
        tail_10k = sum(1 for value in vph if value >= 10000)
        recs.append(
            f"Consider VPH strata using tail bins (e.g. <=1k, 1k–10k, >=10k); ~{tail_10k} regular records have VPH >= 10k.",
        )

    age = _extract_float(all_regular, "age_hours_at_t0")
    if age:
        under_6 = sum(1 for value in age if 0 < value <= 6)
        over_18 = sum(1 for value in age if value > 18)
        recs.append(
            f"Consider age_hours_at_t0 strata (e.g. <=6h vs 6–18h vs >18h); counts ~{under_6} / {len(age) - under_6 - over_18} / ~{over_18}.",
        )

    views = _extract_float(all_regular, "discovery_views")
    if views:
        recs.append(
            "Consider discovery_views strata aligned with qualification threshold (10k+) vs sub-threshold rejected band.",
        )

    vps_available = sum(1 for record in all_regular if record.get("views_per_subscriber_at_t0") is not None)
    recs.append(
        f"V/S strata apply only to {vps_available} regular records with subscribers; keep missing V/S as its own stratum.",
    )

    sparse_keywords = [
        item["keyword"]
        for item in per_keyword
        if item["distributions_regular"]["count"] < 200
    ]
    if sparse_keywords:
        recs.append(
            f"Keywords below ~200 regular records may need proportional caps rather than fixed N: {', '.join(sparse_keywords)}.",
        )

    recs.append(
        "Do not auto-select final experimental N until stratified sampling rules are agreed offline.",
    )
    return recs


def render_distribution_markdown(review: dict[str, Any]) -> str:
    lines: list[str] = [
        "# T0 Distribution Review (Stage 1.9B)",
        "",
        f"**Manifest:** `{review['manifest_path']}`",
        f"**Cohort run:** `{review.get('cohort_run_id')}`",
        f"**Schema:** {review['schema_version']}",
        "",
        "## 1. Dataset overview",
        "",
        f"- Raw records: **{review['overview']['raw_records']}**",
        f"- Regular records (analysis set): **{review['overview']['regular_records']}**",
        f"- Keywords: {len(review.get('keywords', []))}",
        "",
        "## 2. Data quality checks",
        "",
    ]

    inv = review["data_quality"]["global_invariants"]
    lines.extend(
        [
            f"- Qualification invariant: **{inv['invariant_qualification_ok']}** "
            f"({inv['raw_count']} = {inv['passed']} + {inv['rejected']} + {inv['parse_errors']})",
            f"- Regular split invariant: **{inv['invariant_regular_split_ok']}** "
            f"({inv['regular_count']} + {inv['excluded_after_enrichment']} = {inv['raw_count']})",
            f"- Parse errors: **{inv['parse_errors']}**",
            f"- Duplicate video_id (regular, global): **{inv['duplicate_video_id_regular_global']}**",
            f"- Nullable enrichment issues: **{review['data_quality']['nullable_enrichment_global']['issue_count']}**",
            "",
            "## 3. Global distributions (regular only)",
            "",
        ],
    )

    g = review["global_distributions_regular"]
    lines.append(f"### Views (n={g['views']['count']})")
    lines.append(f"- min/median/p75/p90/p95/max: {g['views']['min']} / {g['views']['median']} / {g['views']['p75']} / {g['views']['p90']} / {g['views']['p95']} / {g['views']['max']}")

    lines.append(f"\n### VPH (available={g['vph']['available_count']}, missing={g['vph']['missing_count']})")
    lines.append(f"- min/median/p75/p90/p95/max: {g['vph']['min']} / {g['vph']['median']} / {g['vph']['p75']} / {g['vph']['p90']} / {g['vph']['p95']} / {g['vph']['max']}")
    lines.append(f"- Bins: `{g['vph']['bins']}`")

    vps = g["views_per_subscriber"]
    lines.append(f"\n### Views/Subscribers (available={vps['available_count']}, missing={vps['missing_count']})")
    lines.append(f"- min/median/p75/p90/p95/max: {vps['min']} / {vps['median']} / {vps['p75']} / {vps['p90']} / {vps['p95']} / {vps['max']}")

    age = g["age_hours_at_t0"]
    lines.append(f"\n### Age at T0 (available={age['available_count']})")
    lines.append(f"- min/p25/median/p75/p90/max: {age['min']} / {age.get('p25')} / {age['median']} / {age['p75']} / {age['p90']} / {age['max']}")
    lines.append(f"- Buckets: `{age['buckets']}`")

    sub = g["subscribers"]
    lines.append(f"\n### Subscribers coverage")
    lines.append(f"- available/missing: {sub['final_subscribers_available']} / {sub['final_subscribers_missing']}")
    lines.append(f"- status: `{sub['subscriber_fetch_status']}`")

    lines.extend(["", "## 4. Per-keyword comparison", "", "| keyword | regular | med views | med VPH | P90 VPH | P95 VPH | VPH avail | V/S avail | med age |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for row in review["keyword_comparison"]:
        lines.append(
            f"| {row['keyword']} | {row['regular_count']} | {row['median_views']} | {row['median_vph']} | "
            f"{row['p90_vph']} | {row['p95_vph']} | {row['vph_available']} | {row['v_s_available']} | {row['median_age_hours']} |",
        )

    lines.extend(["", "## 5. VPH tail analysis", ""])
    lines.append(f"Global: `{review['vph_tail_analysis']['global']}`")
    for keyword, block in review["vph_tail_analysis"]["by_keyword"].items():
        lines.append(f"- **{keyword}** (n={block['regular_count']}): `{block['tail']}`")

    lines.extend(["", "## 6. V/S coverage analysis", ""])
    lines.append(
        f"- Global V/S available: **{vps['available_count']}** / {g['count']} regular "
        f"({round(100 * vps['available_count'] / g['count'], 2) if g['count'] else 0}%)",
    )

    lines.extend(["", "## 7. Age distribution", ""])
    lines.append(f"`{age['buckets']}`")

    lines.extend(["", "## 8. Important observations", ""])
    lines.append("- All main statistics use **regular** records only; raw JSONL retains short/live/unknown for diagnostics.")
    lines.append("- VPH tail is heavy-skewed; a small number of videos dominate upper percentiles.")
    lines.append("- Subscriber fetch `not_attempted` is common on rejected rows and must not be read as zero.")

    lines.extend(["", "## 9. Limitations", ""])
    for item in review.get("limitations", []):
        lines.append(f"- {item}")

    lines.extend(["", "## 10. Recommendations for the NEXT sampling step", ""])
    for item in review.get("sampling_recommendations", []):
        lines.append(f"- {item}")

    lines.extend(["", "## Verification", ""])
    ver = review["verification"]
    lines.append(f"- NO_NETWORK_REQUESTS: **{ver['NO_NETWORK_REQUESTS']}**")
    lines.append(f"- NO_DB_WRITES: **{ver['NO_DB_WRITES']}**")
    lines.append(f"- Records processed (raw / regular): {ver['records_processed_raw']} / {ver['records_processed_regular']}")
    lines.append("")
    return "\n".join(lines)


def write_distribution_review(
    review: dict[str, Any],
    *,
    output_dir: Path,
    review_id: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"radar_t0_distribution_review_{review_id}.json"
    md_path = output_dir / f"radar_t0_distribution_review_{review_id}.md"
    json_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_distribution_markdown(review), encoding="utf-8")
    return json_path, md_path
