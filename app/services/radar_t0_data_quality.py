"""Read-only T0 cohort data quality audit (Stage 1.8.4)."""

from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from app.services.radar_validation_t0_dataset import T0_JSONL_FIELDS

Verdict = Literal["READY", "READY_WITH_CAVEATS", "BLOCKED"]

VPH_SANITY_TOLERANCE = 0.015
VPS_SANITY_TOLERANCE = 0.015

EXTREMELY_HIGH_VPH_THRESHOLD = 20_000.0
EXTREMELY_LOW_VPH_THRESHOLD = 500.0
EXTREMELY_HIGH_VPS_THRESHOLD = 2.0

SUBSCRIBER_STATUSES = ("discovery", "homepage_fetched", "unavailable", "not_attempted")


def load_t0_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load cohort_T0 JSONL records without mutation."""
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            record = json.loads(stripped)
            if not isinstance(record, dict):
                raise ValueError(f"Line {line_number}: expected JSON object")
            records.append(record)
    return records


def _pct(count: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round(100.0 * count / total, 2)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _median_min_max(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "median": None, "max": None}
    return {
        "min": round(min(values), 4),
        "median": round(statistics.median(values), 4),
        "max": round(max(values), 4),
    }


def _count_with_pct(count: int, total: int) -> dict[str, Any]:
    return {"count": count, "pct": _pct(count, total)}


def _example_record(record: dict[str, Any], *, reason: str) -> dict[str, Any]:
    return {
        "video_id": record.get("video_id"),
        "reason": reason,
        "discovery_views": record.get("discovery_views"),
        "discovered_at": record.get("discovered_at"),
        "published_at": record.get("published_at"),
        "age_hours_at_t0": record.get("age_hours_at_t0"),
        "vph_at_t0": record.get("vph_at_t0"),
        "final_subscribers": record.get("final_subscribers"),
        "views_per_subscriber_at_t0": record.get("views_per_subscriber_at_t0"),
        "qualification_state": record.get("qualification_state"),
        "enrichment_status": record.get("enrichment_status"),
    }


def audit_integrity(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    video_ids = [str(record.get("video_id", "")) for record in records]
    unique_video_ids = len(set(video_ids))
    duplicate_video_id_count = total - unique_video_ids

    passed = rejected = parse_errors = 0
    for record in records:
        state = record.get("qualification_state")
        if state == "passed":
            passed += 1
        elif state == "rejected":
            rejected += 1
        elif state == "parse_error":
            parse_errors += 1

    invariant_ok = total == passed + rejected + parse_errors

    return {
        "total_records": total,
        "unique_video_id": unique_video_ids,
        "duplicate_video_id_count": duplicate_video_id_count,
        "passed": passed,
        "rejected": rejected,
        "parse_errors": parse_errors,
        "invariant_ok": invariant_ok,
        "invariant": f"{total} == {passed} + {rejected} + {parse_errors}",
    }


def audit_time_quality(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    published_after_discovered = 0
    negative_age = 0
    zero_age = 0
    under_1h = 0
    under_3h = 0
    under_6h = 0
    under_24h = 0
    gte_24h = 0
    age_values: list[float] = []

    for record in records:
        discovered_at = _parse_iso(record.get("discovered_at"))
        published_at = _parse_iso(record.get("published_at"))
        if discovered_at and published_at and published_at > discovered_at:
            published_after_discovered += 1

        age = record.get("age_hours_at_t0")
        if age is None:
            continue
        age_f = float(age)
        age_values.append(age_f)

        if age_f < 0:
            negative_age += 1
        if age_f == 0:
            zero_age += 1
        if age_f < 1:
            under_1h += 1
        if age_f < 3:
            under_3h += 1
        if age_f < 6:
            under_6h += 1
        if age_f < 24:
            under_24h += 1
        if age_f >= 24:
            gte_24h += 1

    age_base = len(age_values)
    return {
        "published_at_gt_discovered_at": _count_with_pct(published_after_discovered, total),
        "age_hours_at_t0_lt_0": _count_with_pct(negative_age, age_base),
        "age_hours_at_t0_eq_0": _count_with_pct(zero_age, age_base),
        "age_hours_at_t0_lt_1": _count_with_pct(under_1h, age_base),
        "age_hours_at_t0_lt_3": _count_with_pct(under_3h, age_base),
        "age_hours_at_t0_lt_6": _count_with_pct(under_6h, age_base),
        "age_hours_at_t0_lt_24": _count_with_pct(under_24h, age_base),
        "age_hours_at_t0_gte_24": _count_with_pct(gte_24h, age_base),
        "age_hours_available": age_base,
        "age_hours_stats": _median_min_max(age_values),
    }


def _recompute_age_hours(record: dict[str, Any]) -> float | None:
    """
    Recompute age from ISO timestamps when possible.

    Enrichment stores rounded age_hours_at_t0 but computes vph_at_t0 from
    full-precision age — timestamp recomputation matches export-time logic.
    """
    discovered_at = _parse_iso(record.get("discovered_at"))
    published_at = _parse_iso(record.get("published_at"))
    if discovered_at and published_at:
        return (discovered_at - published_at).total_seconds() / 3600.0
    age = record.get("age_hours_at_t0")
    if age is None:
        return None
    return float(age)


def _expected_vph(discovery_views: int, age_hours: float) -> float:
    return round(discovery_views / age_hours, 2)


def _expected_vps(discovery_views: int, final_subscribers: int) -> float:
    return round(discovery_views / final_subscribers, 2)


def audit_vph_quality(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    vph_values: list[float] = []
    vph_lte_zero = 0
    sanity_checked = 0
    sanity_mismatch = 0
    mismatch_examples: list[dict[str, Any]] = []

    for record in records:
        vph = record.get("vph_at_t0")
        if vph is None:
            continue
        vph_f = float(vph)
        vph_values.append(vph_f)
        if vph_f <= 0:
            vph_lte_zero += 1

        views = record.get("discovery_views")
        age_hours = _recompute_age_hours(record)
        if vph is not None and age_hours is not None and views is not None and age_hours > 0:
            expected = _expected_vph(int(views), age_hours)
            sanity_checked += 1
            if abs(vph_f - expected) > VPH_SANITY_TOLERANCE:
                sanity_mismatch += 1
                if len(mismatch_examples) < 5:
                    mismatch_examples.append(
                        {
                            "video_id": record.get("video_id"),
                            "vph_at_t0": vph_f,
                            "expected_vph": expected,
                            "discovery_views": views,
                            "age_hours_at_t0": record.get("age_hours_at_t0"),
                            "recomputed_age_hours": round(age_hours, 6),
                        },
                    )

    vph_available = len(vph_values)
    return {
        "vph_available": vph_available,
        "vph_missing": total - vph_available,
        "vph_lte_0": vph_lte_zero,
        "vph_stats": _median_min_max(vph_values),
        "arithmetic_sanity": {
            "checked": sanity_checked,
            "mismatch_count": sanity_mismatch,
            "mismatch_pct": _pct(sanity_mismatch, sanity_checked),
            "tolerance": VPH_SANITY_TOLERANCE,
            "examples": mismatch_examples,
        },
    }


def _subscriber_breakdown(records: list[dict[str, Any]]) -> dict[str, int]:
    breakdown = {status: 0 for status in SUBSCRIBER_STATUSES}
    other = 0
    for record in records:
        status = record.get("subscriber_fetch_status")
        if status in breakdown:
            breakdown[status] += 1
        elif status is None:
            other += 1
        else:
            other += 1
    if other:
        breakdown["other"] = other
    return breakdown


def _subscriber_availability(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    available = sum(
        1
        for record in records
        if record.get("final_subscribers") is not None
    )
    return {
        "available": available,
        "missing": total - available,
        "available_pct": _pct(available, total),
        "status_breakdown": _subscriber_breakdown(records),
    }


def audit_subscriber_enrichment(records: list[dict[str, Any]]) -> dict[str, Any]:
    passed = [r for r in records if r.get("qualification_state") == "passed"]
    rejected = [r for r in records if r.get("qualification_state") == "rejected"]

    total = len(records)
    available = sum(1 for r in records if r.get("final_subscribers") is not None)

    return {
        "final_subscribers_available": available,
        "final_subscribers_missing": total - available,
        "subscriber_fetch_status_breakdown": _subscriber_breakdown(records),
        "by_group": {
            "all": _subscriber_availability(records),
            "passed": _subscriber_availability(passed),
            "rejected": _subscriber_availability(rejected),
        },
    }


def audit_views_per_subscriber(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    vps_values: list[float] = []
    vps_lte_zero = 0
    sanity_checked = 0
    sanity_mismatch = 0
    mismatch_examples: list[dict[str, Any]] = []

    for record in records:
        vps = record.get("views_per_subscriber_at_t0")
        if vps is None:
            continue
        vps_f = float(vps)
        vps_values.append(vps_f)
        if vps_f <= 0:
            vps_lte_zero += 1

        views = record.get("discovery_views")
        subs = record.get("final_subscribers")
        if vps is not None and views is not None and subs is not None and int(subs) > 0:
            expected = _expected_vps(int(views), int(subs))
            sanity_checked += 1
            if abs(vps_f - expected) > VPS_SANITY_TOLERANCE:
                sanity_mismatch += 1
                if len(mismatch_examples) < 5:
                    mismatch_examples.append(
                        {
                            "video_id": record.get("video_id"),
                            "views_per_subscriber_at_t0": vps_f,
                            "expected": expected,
                            "discovery_views": views,
                            "final_subscribers": subs,
                        },
                    )

    available = len(vps_values)
    return {
        "views_per_subscriber_available": available,
        "views_per_subscriber_missing": total - available,
        "views_per_subscriber_lte_0": vps_lte_zero,
        "views_per_subscriber_stats": _median_min_max(vps_values),
        "arithmetic_sanity": {
            "checked": sanity_checked,
            "mismatch_count": sanity_mismatch,
            "mismatch_pct": _pct(sanity_mismatch, sanity_checked),
            "tolerance": VPS_SANITY_TOLERANCE,
            "examples": mismatch_examples,
        },
    }


def audit_format_quality(records: list[dict[str, Any]]) -> dict[str, Any]:
    format_counts = {"regular": 0, "short": 0, "live": 0, "unknown": 0}
    format_violations = 0

    for record in records:
        content_format = record.get("content_format")
        if content_format in format_counts:
            format_counts[content_format] += 1
        else:
            format_counts["unknown"] += 1

        if record.get("is_short") or record.get("is_live"):
            format_violations += 1

    return {
        "content_format_breakdown": format_counts,
        "format_violations": format_violations,
        "expected_validation_cohort": {
            "regular": len(records),
            "short": 0,
            "live": 0,
            "unknown": 0,
        },
        "matches_expected_validation_cohort": (
            format_counts["regular"] == len(records)
            and format_counts["short"] == 0
            and format_counts["live"] == 0
            and format_counts["unknown"] == 0
            and format_violations == 0
        ),
    }


def audit_consistency(records: list[dict[str, Any]]) -> dict[str, Any]:
    missing_discovery_views = 0
    missing_discovered_at = 0
    missing_video_id = 0
    keywords: set[str] = set()

    for record in records:
        if record.get("discovery_views") is None:
            missing_discovery_views += 1
        if not record.get("discovered_at"):
            missing_discovered_at += 1
        if not record.get("video_id"):
            missing_video_id += 1
        keyword = record.get("keyword")
        if keyword:
            keywords.add(str(keyword))

    schema_field_coverage: dict[str, int] = {}
    for field in T0_JSONL_FIELDS:
        schema_field_coverage[field] = sum(1 for record in records if field in record)

    return {
        "discovery_views_present": len(records) - missing_discovery_views,
        "discovery_views_missing": missing_discovery_views,
        "discovered_at_present": len(records) - missing_discovered_at,
        "discovered_at_missing": missing_discovered_at,
        "video_id_present": len(records) - missing_video_id,
        "unique_keywords": sorted(keywords),
        "schema_field_coverage": schema_field_coverage,
        "enrichment_did_not_mutate_discovery_views": "cannot verify from dataset alone",
        "enrichment_did_not_mutate_discovered_at": "cannot verify from dataset alone",
        "video_id_immutable": "cannot verify from dataset alone",
        "keyword_immutable": "cannot verify from dataset alone",
    }


def audit_outliers(records: list[dict[str, Any]]) -> dict[str, Any]:
    negative_age: list[dict[str, Any]] = []
    extremely_high_vph: list[dict[str, Any]] = []
    extremely_low_vph: list[dict[str, Any]] = []
    extremely_high_vps: list[dict[str, Any]] = []
    zero_subs_nonnull_vps: list[dict[str, Any]] = []
    missing_vph_valid_age: list[dict[str, Any]] = []
    missing_final_subscribers: list[dict[str, Any]] = []

    for record in records:
        age = record.get("age_hours_at_t0")
        vph = record.get("vph_at_t0")
        vps = record.get("views_per_subscriber_at_t0")
        views = record.get("discovery_views")
        subs = record.get("final_subscribers")

        if age is not None and float(age) < 0:
            negative_age.append(_example_record(record, reason="negative_age"))

        if vph is not None and float(vph) >= EXTREMELY_HIGH_VPH_THRESHOLD:
            extremely_high_vph.append(_example_record(record, reason="extremely_high_vph"))

        if vph is not None and 0 < float(vph) <= EXTREMELY_LOW_VPH_THRESHOLD:
            extremely_low_vph.append(_example_record(record, reason="extremely_low_vph"))

        if vps is not None and float(vps) >= EXTREMELY_HIGH_VPS_THRESHOLD:
            extremely_high_vps.append(_example_record(record, reason="extremely_high_vps"))

        if (subs == 0 or subs is None) and vps is not None:
            zero_subs_nonnull_vps.append(_example_record(record, reason="zero_subs_nonnull_vps"))

        if (
            age is not None
            and float(age) > 0
            and views is not None
            and int(views) > 0
            and vph is None
        ):
            missing_vph_valid_age.append(_example_record(record, reason="missing_vph_valid_age"))

        if subs is None:
            missing_final_subscribers.append(_example_record(record, reason="missing_final_subscribers"))

    def _top5(items: list[dict[str, Any]], *, sort_key: str | None = None, reverse: bool = True) -> list[dict[str, Any]]:
        if sort_key:
            items = sorted(items, key=lambda item: float(item.get(sort_key) or 0), reverse=reverse)
        return items[:5]

    extremely_high_vph_sorted = sorted(
        extremely_high_vph,
        key=lambda item: float(item.get("vph_at_t0") or 0),
        reverse=True,
    )
    extremely_low_vph_sorted = sorted(
        extremely_low_vph,
        key=lambda item: float(item.get("vph_at_t0") or 0),
    )
    extremely_high_vps_sorted = sorted(
        extremely_high_vps,
        key=lambda item: float(item.get("views_per_subscriber_at_t0") or 0),
        reverse=True,
    )

    return {
        "negative_age": {"count": len(negative_age), "examples": _top5(negative_age)},
        "extremely_high_vph": {
            "threshold": EXTREMELY_HIGH_VPH_THRESHOLD,
            "count": len(extremely_high_vph),
            "examples": _top5(extremely_high_vph_sorted),
        },
        "extremely_low_vph": {
            "threshold": EXTREMELY_LOW_VPH_THRESHOLD,
            "count": len(extremely_low_vph),
            "examples": _top5(extremely_low_vph_sorted, reverse=False),
        },
        "extremely_high_views_per_subscriber": {
            "threshold": EXTREMELY_HIGH_VPS_THRESHOLD,
            "count": len(extremely_high_vps),
            "examples": _top5(extremely_high_vps_sorted),
        },
        "zero_subscribers_with_nonnull_vps": {
            "count": len(zero_subs_nonnull_vps),
            "examples": _top5(zero_subs_nonnull_vps),
        },
        "missing_vph_despite_valid_age_views": {
            "count": len(missing_vph_valid_age),
            "examples": _top5(missing_vph_valid_age),
        },
        "missing_final_subscribers": {
            "count": len(missing_final_subscribers),
            "examples": _top5(missing_final_subscribers),
        },
    }


def _build_caveats(audit: dict[str, Any]) -> list[dict[str, Any]]:
    caveats: list[dict[str, Any]] = []
    total = audit["integrity"]["total_records"]

    integrity = audit["integrity"]
    if not integrity["invariant_ok"]:
        caveats.append(
            {
                "problem": "Qualification invariant failed",
                "affected_records": total,
                "why_it_matters": "Dataset counts are internally inconsistent",
                "blocks_next_stage": True,
            },
        )

    if integrity["duplicate_video_id_count"] > 0:
        caveats.append(
            {
                "problem": "Duplicate video_id values",
                "affected_records": integrity["duplicate_video_id_count"],
                "why_it_matters": "T0 cohort should be one row per discovered video",
                "blocks_next_stage": True,
            },
        )

    fmt = audit["format"]
    if not fmt["matches_expected_validation_cohort"]:
        affected = fmt["format_violations"] + fmt["content_format_breakdown"].get("short", 0) + fmt["content_format_breakdown"].get("live", 0)
        caveats.append(
            {
                "problem": "Format classification deviates from validation-only regular cohort",
                "affected_records": affected,
                "why_it_matters": "Validation scan excludes Shorts/LIVE at discovery",
                "blocks_next_stage": True,
            },
        )

    time_q = audit["time_quality"]
    neg = time_q["age_hours_at_t0_lt_0"]["count"]
    pub_after = time_q["published_at_gt_discovered_at"]["count"]
    if neg > 0 or pub_after > 0:
        caveats.append(
            {
                "problem": "Negative age or published_at after discovered_at (API/Innertube clock skew)",
                "affected_records": max(neg, pub_after),
                "why_it_matters": "VPH is null or unreliable when publish time is after discovery snapshot",
                "blocks_next_stage": False,
            },
        )

    vph_sanity = audit["vph_quality"]["arithmetic_sanity"]
    if vph_sanity["mismatch_count"] > 0:
        caveats.append(
            {
                "problem": "VPH arithmetic sanity mismatches",
                "affected_records": vph_sanity["mismatch_count"],
                "why_it_matters": "Stored vph_at_t0 may not match discovery_views/age_hours_at_t0",
                "blocks_next_stage": True,
            },
        )

    vps_sanity = audit["views_per_subscriber"]["arithmetic_sanity"]
    if vps_sanity["mismatch_count"] > 0:
        caveats.append(
            {
                "problem": "Views/subscriber arithmetic sanity mismatches",
                "affected_records": vps_sanity["mismatch_count"],
                "why_it_matters": "Stored views_per_subscriber_at_t0 may not match discovery_views/final_subscribers",
                "blocks_next_stage": True,
            },
        )

    subs = audit["subscriber_enrichment"]
    not_attempted = subs["subscriber_fetch_status_breakdown"].get("not_attempted", 0)
    if not_attempted > 0:
        caveats.append(
            {
                "problem": "Subscriber fetch not attempted for many channels",
                "affected_records": not_attempted,
                "why_it_matters": "final_subscribers and views_per_subscriber_at_t0 unavailable for viral coefficient at T0",
                "blocks_next_stage": False,
            },
        )

    unavailable = subs["subscriber_fetch_status_breakdown"].get("unavailable", 0)
    if unavailable > 0:
        caveats.append(
            {
                "problem": "Subscriber fetch attempted but unavailable",
                "affected_records": unavailable,
                "why_it_matters": "Channel homepage did not yield subscriber count; distinct from not_attempted",
                "blocks_next_stage": False,
            },
        )

    outliers = audit["outliers"]
    if outliers["zero_subscribers_with_nonnull_vps"]["count"] > 0:
        caveats.append(
            {
                "problem": "Non-null views_per_subscriber with zero/missing final_subscribers",
                "affected_records": outliers["zero_subscribers_with_nonnull_vps"]["count"],
                "why_it_matters": "Data consistency bug in enrichment layer",
                "blocks_next_stage": True,
            },
        )

    if outliers["missing_vph_despite_valid_age_views"]["count"] > 0:
        caveats.append(
            {
                "problem": "Missing VPH despite positive age and views",
                "affected_records": outliers["missing_vph_despite_valid_age_views"]["count"],
                "why_it_matters": "Expected by design when age_hours_at_t0 <= 0; verify count stays small",
                "blocks_next_stage": False,
            },
        )

    return caveats


def determine_verdict(audit: dict[str, Any], caveats: list[dict[str, Any]]) -> Verdict:
    if any(c["blocks_next_stage"] for c in caveats):
        blocking = [c for c in caveats if c["blocks_next_stage"]]
        if any(
            c["problem"]
            in {
                "Qualification invariant failed",
                "Duplicate video_id values",
                "Format classification deviates from validation-only regular cohort",
                "VPH arithmetic sanity mismatches",
                "Views/subscriber arithmetic sanity mismatches",
                "Non-null views_per_subscriber with zero/missing final_subscribers",
            }
            for c in blocking
        ):
            return "BLOCKED"
    if caveats:
        return "READY_WITH_CAVEATS"
    return "READY"


def audit_t0_dataset(records: list[dict[str, Any]], *, source_path: str) -> dict[str, Any]:
    """Run full read-only quality audit on loaded T0 JSONL records."""
    keyword = records[0].get("keyword") if records else None

    audit: dict[str, Any] = {
        "source_path": source_path,
        "keyword": keyword,
        "overview": {
            "total_records": len(records),
            "keyword": keyword,
        },
        "integrity": audit_integrity(records),
        "time_quality": audit_time_quality(records),
        "vph_quality": audit_vph_quality(records),
        "subscriber_enrichment": audit_subscriber_enrichment(records),
        "views_per_subscriber": audit_views_per_subscriber(records),
        "format": audit_format_quality(records),
        "consistency": audit_consistency(records),
        "outliers": audit_outliers(records),
    }

    caveats = _build_caveats(audit)
    audit["caveats"] = caveats
    audit["final_verdict"] = determine_verdict(audit, caveats)
    return audit


def render_markdown_report(audit: dict[str, Any]) -> str:
    """Render human-readable markdown audit report."""
    lines: list[str] = [
        "# T0 Data Quality Audit",
        "",
        f"**Source:** `{audit['source_path']}`",
        f"**Keyword:** {audit.get('keyword')}",
        f"**Final verdict:** `{audit['final_verdict']}`",
        "",
        "## 1. Dataset overview",
        "",
        f"- Total records: **{audit['overview']['total_records']}**",
        "",
        "## 2. Integrity",
        "",
    ]

    integrity = audit["integrity"]
    lines.extend(
        [
            f"- Total records: {integrity['total_records']}",
            f"- Unique video_id: {integrity['unique_video_id']}",
            f"- Duplicate video_id count: {integrity['duplicate_video_id_count']}",
            f"- Passed: {integrity['passed']}",
            f"- Rejected: {integrity['rejected']}",
            f"- Parse errors: {integrity['parse_errors']}",
            f"- Invariant OK: **{integrity['invariant_ok']}** (`{integrity['invariant']}`)",
            "",
            "## 3. Time quality",
            "",
        ],
    )

    time_q = audit["time_quality"]
    for key in (
        "published_at_gt_discovered_at",
        "age_hours_at_t0_lt_0",
        "age_hours_at_t0_eq_0",
        "age_hours_at_t0_lt_1",
        "age_hours_at_t0_lt_3",
        "age_hours_at_t0_lt_6",
        "age_hours_at_t0_lt_24",
        "age_hours_at_t0_gte_24",
    ):
        bucket = time_q[key]
        lines.append(f"- `{key}`: {bucket['count']} ({bucket['pct']}%)")

    stats = time_q["age_hours_stats"]
    lines.extend(
        [
            f"- Age min/median/max: {stats['min']} / {stats['median']} / {stats['max']} hours",
            "",
            "## 4. VPH quality",
            "",
        ],
    )

    vph = audit["vph_quality"]
    lines.extend(
        [
            f"- VPH available: {vph['vph_available']}",
            f"- VPH missing: {vph['vph_missing']}",
            f"- VPH <= 0: {vph['vph_lte_0']}",
            f"- VPH min/median/max: {vph['vph_stats']['min']} / {vph['vph_stats']['median']} / {vph['vph_stats']['max']}",
            f"- Arithmetic sanity mismatches: {vph['arithmetic_sanity']['mismatch_count']} / {vph['arithmetic_sanity']['checked']}",
            "",
            "## 5. Subscriber enrichment",
            "",
        ],
    )

    subs = audit["subscriber_enrichment"]
    lines.extend(
        [
            f"- final_subscribers available: {subs['final_subscribers_available']}",
            f"- final_subscribers missing: {subs['final_subscribers_missing']}",
            f"- Status breakdown: `{subs['subscriber_fetch_status_breakdown']}`",
            "",
            "### By qualification group",
            "",
        ],
    )
    for group_name, group in subs["by_group"].items():
        lines.append(
            f"- **{group_name}**: available={group['available']} ({group['available_pct']}%), "
            f"missing={group['missing']}, breakdown={group['status_breakdown']}",
        )

    vps = audit["views_per_subscriber"]
    lines.extend(
        [
            "",
            "## 6. Views/Subscribers",
            "",
            f"- views_per_subscriber available: {vps['views_per_subscriber_available']}",
            f"- missing: {vps['views_per_subscriber_missing']}",
            f"- <= 0: {vps['views_per_subscriber_lte_0']}",
            f"- min/median/max: {vps['views_per_subscriber_stats']['min']} / {vps['views_per_subscriber_stats']['median']} / {vps['views_per_subscriber_stats']['max']}",
            f"- Arithmetic sanity mismatches: {vps['arithmetic_sanity']['mismatch_count']} / {vps['arithmetic_sanity']['checked']}",
            "",
            "## 7. Format quality",
            "",
        ],
    )

    fmt = audit["format"]
    lines.extend(
        [
            f"- Content format breakdown: `{fmt['content_format_breakdown']}`",
            f"- format_violations (is_short/is_live): {fmt['format_violations']}",
            f"- Matches expected validation cohort: **{fmt['matches_expected_validation_cohort']}**",
            "",
            "## 8. Consistency",
            "",
        ],
    )

    consistency = audit["consistency"]
    lines.extend(
        [
            f"- discovery_views present/missing: {consistency['discovery_views_present']} / {consistency['discovery_views_missing']}",
            f"- discovered_at present/missing: {consistency['discovered_at_present']} / {consistency['discovered_at_missing']}",
            f"- Unique keywords: {consistency['unique_keywords']}",
            f"- enrichment did not mutate discovery_views: {consistency['enrichment_did_not_mutate_discovery_views']}",
            f"- enrichment did not mutate discovered_at: {consistency['enrichment_did_not_mutate_discovered_at']}",
            f"- video_id immutable: {consistency['video_id_immutable']}",
            f"- keyword immutable: {consistency['keyword_immutable']}",
            "",
            "## 9. Outliers",
            "",
        ],
    )

    for name, block in audit["outliers"].items():
        count = block["count"]
        lines.append(f"- **{name}**: {count}")
        for example in block.get("examples", [])[:3]:
            lines.append(f"  - `{example.get('video_id')}`: {example}")

    lines.extend(["", "## 10. Final verdict", "", f"**{audit['final_verdict']}**", ""])

    if audit["caveats"]:
        lines.append("### Caveats")
        lines.append("")
        for caveat in audit["caveats"]:
            block_flag = "BLOCKS" if caveat["blocks_next_stage"] else "non-blocking"
            lines.append(
                f"- **{caveat['problem']}** — {caveat['affected_records']} records ({block_flag}): "
                f"{caveat['why_it_matters']}",
            )
    else:
        lines.append("No caveats identified.")

    lines.append("")
    return "\n".join(lines)


def write_audit_reports(
    audit: dict[str, Any],
    *,
    output_dir: Path,
    keyword: str | None = None,
    timestamp: datetime | None = None,
) -> tuple[Path, Path]:
    """Write JSON and Markdown audit reports."""
    from datetime import timezone

    ts = timestamp or datetime.now(timezone.utc)
    stamp = ts.strftime("%Y%m%d_%H%M%S")
    safe_keyword = (keyword or audit.get("keyword") or "dataset").strip().lower()
    safe_keyword = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in safe_keyword)

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"radar_t0_quality_audit_{safe_keyword}_{stamp}.json"
    md_path = output_dir / f"radar_t0_quality_audit_{safe_keyword}_{stamp}.md"

    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown_report(audit), encoding="utf-8")
    return json_path, md_path
