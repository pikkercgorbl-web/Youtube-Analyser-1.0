"""Tests for T0 data quality audit (Stage 1.8.4)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.radar_t0_data_quality import (
    audit_format_quality,
    audit_integrity,
    audit_subscriber_enrichment,
    audit_time_quality,
    audit_t0_dataset,
    audit_vph_quality,
    audit_views_per_subscriber,
)


def _record(**overrides: object) -> dict:
    base = {
        "video_id": "vid1",
        "channel_id": "UC123",
        "keyword": "gaming",
        "video_title": "Title",
        "channel_title": "Channel",
        "discovered_at": "2026-09-11T17:24:19+00:00",
        "discovery_views": 10_000,
        "discovery_subscribers": 0,
        "discovery_published_text": "2 hours ago",
        "discovery_source": "innertube",
        "is_short": False,
        "is_live": False,
        "content_renderer": "videoRenderer",
        "final_subscribers": 2000,
        "subscriber_fetch_status": "homepage_fetched",
        "published_at": "2026-09-11T15:24:19+00:00",
        "age_hours_at_t0": 2.0,
        "vph_at_t0": 5000.0,
        "views_per_subscriber_at_t0": 5.0,
        "duration_seconds": 600,
        "content_format": "regular",
        "enrichment_status": "ok",
        "qualification_state": "passed",
        "first_failure_reason": None,
    }
    base.update(overrides)
    return base


def test_integrity_invariant() -> None:
    records = [
        _record(video_id="a", qualification_state="passed"),
        _record(video_id="b", qualification_state="rejected", first_failure_reason="min_views"),
        _record(video_id="c", qualification_state="parse_error", first_failure_reason="parse_error"),
    ]
    result = audit_integrity(records)
    assert result["total_records"] == 3
    assert result["passed"] == 1
    assert result["rejected"] == 1
    assert result["parse_errors"] == 1
    assert result["invariant_ok"] is True


def test_negative_age_detection() -> None:
    records = [_record(age_hours_at_t0=-0.5, vph_at_t0=None)]
    result = audit_time_quality(records)
    assert result["age_hours_at_t0_lt_0"]["count"] == 1


def test_age_bucket_calculation() -> None:
    records = [
        _record(video_id="a", age_hours_at_t0=0.5),
        _record(video_id="b", age_hours_at_t0=2.0),
        _record(video_id="c", age_hours_at_t0=25.0),
    ]
    result = audit_time_quality(records)
    assert result["age_hours_at_t0_lt_1"]["count"] == 1
    assert result["age_hours_at_t0_lt_24"]["count"] == 2
    assert result["age_hours_at_t0_gte_24"]["count"] == 1


def test_vph_availability() -> None:
    records = [
        _record(video_id="a", vph_at_t0=100.0),
        _record(video_id="b", vph_at_t0=None, age_hours_at_t0=-1.0),
    ]
    result = audit_vph_quality(records)
    assert result["vph_available"] == 1
    assert result["vph_missing"] == 1


def test_vph_arithmetic_sanity() -> None:
    records = [_record(discovery_views=10_000, age_hours_at_t0=2.0, vph_at_t0=5000.0)]
    result = audit_vph_quality(records)
    assert result["arithmetic_sanity"]["mismatch_count"] == 0

    bad = [_record(discovery_views=10_000, age_hours_at_t0=2.0, vph_at_t0=9999.0)]
    bad_result = audit_vph_quality(bad)
    assert bad_result["arithmetic_sanity"]["mismatch_count"] == 1


def test_subscriber_status_breakdown() -> None:
    records = [
        _record(video_id="a", subscriber_fetch_status="discovery", final_subscribers=100),
        _record(video_id="b", subscriber_fetch_status="homepage_fetched", final_subscribers=200),
        _record(video_id="c", subscriber_fetch_status="not_attempted", final_subscribers=None),
        _record(video_id="d", subscriber_fetch_status="unavailable", final_subscribers=None),
    ]
    result = audit_subscriber_enrichment(records)
    breakdown = result["subscriber_fetch_status_breakdown"]
    assert breakdown["discovery"] == 1
    assert breakdown["homepage_fetched"] == 1
    assert breakdown["not_attempted"] == 1
    assert breakdown["unavailable"] == 1
    assert result["final_subscribers_available"] == 2


def test_views_per_subscriber_sanity() -> None:
    records = [_record(discovery_views=10_000, final_subscribers=2000, views_per_subscriber_at_t0=5.0)]
    result = audit_views_per_subscriber(records)
    assert result["arithmetic_sanity"]["mismatch_count"] == 0


def test_format_breakdown() -> None:
    records = [
        _record(video_id="a", content_format="regular"),
        _record(video_id="b", content_format="short", is_short=True),
    ]
    result = audit_format_quality(records)
    assert result["content_format_breakdown"]["regular"] == 1
    assert result["content_format_breakdown"]["short"] == 1
    assert result["format_violations"] == 1


def test_missing_null_handling() -> None:
    records = [
        _record(
            final_subscribers=None,
            subscriber_fetch_status="not_attempted",
            views_per_subscriber_at_t0=None,
            vph_at_t0=None,
            age_hours_at_t0=None,
            published_at=None,
        ),
    ]
    audit = audit_t0_dataset(records, source_path="test.jsonl")
    assert audit["vph_quality"]["vph_missing"] == 1
    assert audit["subscriber_enrichment"]["final_subscribers_missing"] == 1
    assert audit["views_per_subscriber"]["views_per_subscriber_missing"] == 1


async def main() -> None:
    tests = [
        test_integrity_invariant,
        test_negative_age_detection,
        test_age_bucket_calculation,
        test_vph_availability,
        test_vph_arithmetic_sanity,
        test_subscriber_status_breakdown,
        test_views_per_subscriber_sanity,
        test_format_breakdown,
        test_missing_null_handling,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"OK {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")

    if failed:
        raise SystemExit(f"{failed} test(s) failed")
    print("All T0 data quality audit tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
