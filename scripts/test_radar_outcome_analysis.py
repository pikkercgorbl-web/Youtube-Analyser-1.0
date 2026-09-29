"""Tests for offline T0 → T67 outcome analysis (Stage 1.9D)."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.radar_outcome_analysis import (
    build_joined_dataset,
    extract_top_winners,
    keyword_analysis,
    percentile_stats,
    qualification_comparison,
    run_outcome_analysis,
    spearman_correlation,
)


def _snap(**kwargs: object) -> dict:
    base = {
        "video_id": "v1",
        "t0_keywords": ["gaming"],
        "t0_views": 1000,
        "t0_vph": 500.0,
        "t0_views_per_subscriber": None,
        "t0_final_subscribers": None,
        "t0_age_hours": 10.0,
        "t0_content_format": "regular",
        "t0_qualification_outcome": "rejected",
        "t0_filter_reason": "min_views",
        "refresh_status": "refreshed",
        "current_views": 2000,
        "absolute_view_growth": 1000,
        "view_growth_multiple": 2.0,
        "avg_growth_views_per_hour": 15.0,
        "elapsed_hours_from_t0": 67.0689,
    }
    base.update(kwargs)
    return base


def test_join_excludes_missing_refresh() -> None:
    rows = [_snap(), _snap(video_id="v2", refresh_status="missing", absolute_view_growth=None)]
    joined = build_joined_dataset(rows)
    assert len(joined) == 1
    assert joined[0]["video_id"] == "v1"


def test_no_duplicate_video_ids_globally() -> None:
    joined = build_joined_dataset([_snap(), _snap(video_id="v2")])
    assert len({row["video_id"] for row in joined}) == len(joined)


def test_v_s_missing_remains_null() -> None:
    joined = build_joined_dataset([_snap()])
    assert joined[0]["t0_views_per_subscriber"] is None


def test_spearman_helper() -> None:
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = spearman_correlation(xs, ys)
    assert result["rho"] == 1.0


def test_percentile_grouping() -> None:
    stats = percentile_stats([1.0, 2.0, 3.0, 4.0, 100.0], include_p99=True)
    assert stats["p90"] <= stats["p99"]


def test_qualification_comparison() -> None:
    joined = build_joined_dataset(
        [
            _snap(video_id="p", t0_qualification_outcome="passed", absolute_view_growth=5000),
            _snap(video_id="r", t0_qualification_outcome="rejected", absolute_view_growth=100),
        ],
    )
    result = qualification_comparison(joined)
    assert result["passed"]["n"] == 1
    assert result["rejected"]["n"] == 1


def test_keyword_multi_membership() -> None:
    joined = build_joined_dataset([_snap(t0_keywords=["gaming", "travel"])])
    kw = keyword_analysis(joined)
    assert kw["multi_keyword_membership_allowed"] is True
    assert kw["keywords"]["gaming"]["n_membership_rows"] == 1
    assert kw["keywords"]["travel"]["n_membership_rows"] == 1


def test_negative_growth_preserved() -> None:
    joined = build_joined_dataset([_snap(absolute_view_growth=-10, current_views=990)])
    assert joined[0]["absolute_view_growth"] == -10


def test_top_winner_extraction() -> None:
    joined = build_joined_dataset(
        [
            _snap(video_id="low", absolute_view_growth=10),
            _snap(video_id="high", absolute_view_growth=1000),
        ],
    )
    top = extract_top_winners(joined, limit=1)
    assert top[0]["video_id"] == "high"


def test_end_to_end_mini_analysis() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        snapshot = tmp_path / "snap.jsonl"
        snapshot.write_text(
            "\n".join(
                [
                    json.dumps(_snap()),
                    json.dumps(_snap(video_id="m", refresh_status="missing")),
                ],
            ),
            encoding="utf-8",
        )
        meta = tmp_path / "meta.json"
        meta.write_text(json.dumps({"elapsed_hours_from_t0": 67.0689}), encoding="utf-8")
        report = run_outcome_analysis(snapshot_path=snapshot, snapshot_meta_path=meta)
        assert report["verification"]["joined_rows"] == 1


async def main() -> None:
    tests = [
        test_join_excludes_missing_refresh,
        test_no_duplicate_video_ids_globally,
        test_v_s_missing_remains_null,
        test_spearman_helper,
        test_percentile_grouping,
        test_qualification_comparison,
        test_keyword_multi_membership,
        test_negative_growth_preserved,
        test_top_winner_extraction,
        test_end_to_end_mini_analysis,
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
    print("All outcome analysis tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
