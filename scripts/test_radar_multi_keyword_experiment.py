"""Smoke tests for multi-keyword radar experiment aggregation (Stage 1.4)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.radar_multi_keyword_report import (
    KeywordExperimentResult,
    aggregate_experiment_results,
    keyword_table_row,
    parse_json_log_line,
    parse_keyword_scan_output,
)


def _sample_log(keyword: str) -> str:
    return "\n".join(
        [
            f"✅ [РАДАР] '{keyword}': сохранено каналов 2 (страниц: 5, прошло фильтры: 2)",
            "[RADAR_INNERTUBE_METRICS] "
            + json.dumps(
                {
                    "keyword": keyword,
                    "request_count": 5,
                    "total_duration_ms": 1200.0,
                    "error_count": 0,
                },
            ),
            "[RADAR_FILTER_METRICS] "
            + json.dumps(
                {
                    "discovered_videos": 100,
                    "filter_skips": 98,
                    "passed_videos": 2,
                    "parse_errors": 0,
                    "filter_skip_reasons": {"min_views": 80, "min_viral_coeff": 18},
                },
            ),
            "[RADAR_CANDIDATE_SUMMARY] "
            + json.dumps(
                {
                    "candidate_count": 100,
                    "passed_count": 2,
                    "rejected_count": 98,
                    "signal_availability": {"vph": 99, "viral_coefficient": 3},
                },
            ),
            "[RADAR_CANDIDATE_DISTRIBUTION] "
            + json.dumps(
                {
                    "signal_availability": {
                        "views": 100,
                        "subscribers": 100,
                        "vph": 99,
                        "viral_coefficient": 3,
                    },
                    "groups": {
                        "all": {
                            "count": 100,
                            "views": {"count": 100, "min": 0, "max": 50000},
                        },
                    },
                },
            ),
        ],
    )


def test_parse_single_keyword_result() -> None:
    result = parse_keyword_scan_output("AI tools", _sample_log("AI tools"))
    assert result.pages == 5
    assert result.innertube["request_count"] == 5
    assert result.filter_metrics["discovered_videos"] == 100
    assert result.candidate_summary["candidate_count"] == 100
    assert result.distribution["groups"]["all"]["count"] == 100


def test_keyword_table_row() -> None:
    result = parse_keyword_scan_output("fitness", _sample_log("fitness"))
    row = keyword_table_row(result)
    assert row["discovered"] == 100
    assert row["candidates"] == 100
    assert row["passed"] == 2
    assert row["rejected"] == 98
    assert row["min_views"] == 80
    assert row["min_viral_coeff"] == 18
    assert row["vph_available"] == 99
    assert row["viral_available"] == 3


def test_aggregate_multiple_keywords() -> None:
    results = [
        parse_keyword_scan_output("AI tools", _sample_log("AI tools")),
        parse_keyword_scan_output("gaming", _sample_log("gaming")),
    ]
    report = aggregate_experiment_results(results)
    assert report["totals"]["total_keywords"] == 2
    assert report["totals"]["total_discovered"] == 200
    assert report["totals"]["total_candidates"] == 200
    assert report["totals"]["total_passed"] == 4
    assert report["totals"]["total_rejected"] == 196


def test_failed_keyword_does_not_break_aggregation() -> None:
    ok = parse_keyword_scan_output("history", _sample_log("history"))
    failed = KeywordExperimentResult(keyword="broken", success=False, error="boom")
    report = aggregate_experiment_results([ok, failed])
    assert report["totals"]["successful_keywords"] == 1
    assert report["totals"]["failed_keywords"] == 1
    assert report["failed_keyword_details"][0]["keyword"] == "broken"


def test_rejection_reason_totals() -> None:
    results = [
        parse_keyword_scan_output("a", _sample_log("a")),
        parse_keyword_scan_output("b", _sample_log("b")),
    ]
    report = aggregate_experiment_results(results)
    assert report["rejection_reasons"]["min_views"] == 160
    assert report["rejection_reasons"]["min_viral_coeff"] == 36


def test_missing_optional_signals_do_not_break_aggregation() -> None:
    log_text = "[RADAR_CANDIDATE_DISTRIBUTION] " + json.dumps({"groups": {"all": {"count": 0}}})
    result = parse_keyword_scan_output("empty", log_text)
    row = keyword_table_row(result)
    assert row["vph_available"] == 0
    assert row["viral_available"] == 0
    report = aggregate_experiment_results([result])
    assert report["totals"]["total_candidates"] == 0


def test_parse_json_log_line() -> None:
    line = '[RADAR_FILTER_METRICS] {"discovered_videos": 10}'
    payload = parse_json_log_line(line, "[RADAR_FILTER_METRICS]")
    assert payload == {"discovered_videos": 10}


def main() -> None:
    tests = [
        test_parse_single_keyword_result,
        test_keyword_table_row,
        test_aggregate_multiple_keywords,
        test_failed_keyword_does_not_break_aggregation,
        test_rejection_reason_totals,
        test_missing_optional_signals_do_not_break_aggregation,
        test_parse_json_log_line,
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
    print("All multi-keyword experiment tests passed.")


if __name__ == "__main__":
    main()
