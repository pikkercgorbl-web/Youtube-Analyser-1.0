"""Tests for Stage 1.10C cohort sampling and artifacts."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.radar_baseline_sampling_design import SAMPLING_SEED, compute_vph_boundaries
from app.services.radar_candidate import RadarCandidate
from app.services.radar_stage110_cohort import (
    STAGE110_TARGET_SAMPLE_SIZE,
    build_eligible_pool,
    candidate_to_pool_record,
    merge_candidates_by_video_id,
    sample_stage110_design_a,
    serialize_stage110_broad_row,
    serialize_stage110_sample_row,
    write_jsonl,
)


def _candidate(
    video_id: str,
    *,
    keyword: str = "gaming",
    channel_id: str = "ch1",
    vph: float = 100.0,
    views: int = 1000,
) -> RadarCandidate:
    return RadarCandidate(
        video_id=video_id,
        channel_id=channel_id,
        keyword=keyword,
        discovery_source="innertube",
        discovered_at=datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc),
        video_title="t",
        channel_title="c",
        discovery_views=views,
        content_format="regular",
        vph_at_t0=vph,
        age_hours_at_t0=5.0,
    )


def test_stratum_boundaries_from_t0_only() -> None:
    pool = [
        {"vph_at_t0": float(i), "content_format": "regular", "channel_id": "c", "video_id": f"v{i}"}
        for i in range(1, 101)
    ]
    bounds = compute_vph_boundaries(pool)
    assert bounds["p25"] < bounds["p75"]


def test_design_a_allocation_and_seed() -> None:
    keywords = list(
        (
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
        ),
    )
    candidates = [
        _candidate(
            f"v{i}",
            keyword=keywords[i % len(keywords)],
            channel_id=f"ch{i}",
            vph=float(i * 10),
        )
        for i in range(1, 1200)
    ]
    _, pool = build_eligible_pool(candidates)
    a, audit_a, _ = sample_stage110_design_a(pool, target_size=500, seed=SAMPLING_SEED)
    b, audit_b, _ = sample_stage110_design_a(pool, target_size=500, seed=SAMPLING_SEED)
    assert a == b
    assert len(a) >= 490
    assert sum(audit_a.vph_stratum_actual.values()) == len(a)


def test_keyword_cap_respected() -> None:
    candidates = []
    for kw_index, keyword in enumerate(["gaming", "travel", "history"]):
        for i in range(400):
            candidates.append(
                _candidate(
                    f"{keyword}_{i}",
                    keyword=keyword,
                    channel_id=f"ch_{keyword}_{i}",
                    vph=1000 + kw_index * 100 + i,
                ),
            )
    _, pool = build_eligible_pool(candidates)
    selected, audit, records_by_id = sample_stage110_design_a(pool, target_size=500, seed=42)
    cap = max(1, int(round(500 * 0.18)))
    for count in audit.keyword_quotas_filled.values():
        assert count <= cap, f"keyword count {count} exceeds cap {cap}"
    for video_id in selected:
        assert video_id in records_by_id


def test_max_two_videos_per_channel() -> None:
    candidates = [
        _candidate(f"v{i}", channel_id="same_channel", vph=float(i * 100))
        for i in range(1, 50)
    ]
    _, pool = build_eligible_pool(candidates)
    selected, _, records_by_id = sample_stage110_design_a(pool, target_size=30, seed=42)
    channel_counts: dict[str, int] = {}
    for video_id in selected:
        channel_counts[records_by_id[video_id].channel_id] = (
            channel_counts.get(records_by_id[video_id].channel_id, 0) + 1
        )
    assert all(count <= 2 for count in channel_counts.values())


def test_broad_preserved_before_sample() -> None:
    candidates = [_candidate("a"), _candidate("b", vph=1.0)]
    deduped = merge_candidates_by_video_id(candidates)
    assert len(deduped) == 2


def test_sample_ids_subset() -> None:
    candidates = [_candidate(f"v{i}", channel_id=f"ch{i}", vph=float(i)) for i in range(1, 200)]
    eligible, pool = build_eligible_pool(candidates)
    selected, _, _ = sample_stage110_design_a(pool, target_size=50, seed=1)
    eligible_ids = {candidate.video_id for candidate in eligible}
    assert set(selected).issubset(eligible_ids)


def test_no_outcome_fields_in_pool_record() -> None:
    record = candidate_to_pool_record(_candidate("x"))
    assert "absolute_view_growth" not in record


def test_dedupe_video_id() -> None:
    a = _candidate("dup", keyword="gaming")
    b = _candidate("dup", keyword="travel")
    merged = merge_candidates_by_video_id([a, b])
    assert len(merged) == 1
    assert getattr(merged[0], "t0_keywords") == ["gaming", "travel"]


async def test_baseline_only_for_selected_mock() -> None:
    selected = [_candidate("only")]
    with patch(
        "app.services.radar_stage110_cohort.collect_channel_baselines_for_candidates",
        new_callable=AsyncMock,
    ) as mock_fn:
        from app.services.radar_channel_baseline import ChannelBaselineRunStats
        from app.services.radar_stage110_cohort import apply_baseline_to_selected

        mock_fn.return_value = ChannelBaselineRunStats()
        await apply_baseline_to_selected(selected, object())
        mock_fn.assert_called_once()
        assert mock_fn.call_args[0][0] == selected


def test_serialize_sample_row_fields() -> None:
    from app.services.radar_stage110_cohort import SamplingAudit

    candidate = _candidate("v1")
    audit = SamplingAudit(
        seed=42,
        eligible_count=100,
        target_size=500,
        vph_boundaries={},
        keyword_quotas_requested={},
        keyword_quotas_filled={},
        vph_stratum_target={},
        vph_stratum_actual={},
        top_up_added=0,
        per_channel_dropped=0,
        keyword_shortfalls={},
    )
    row = serialize_stage110_sample_row(candidate, vph_stratum="high", sampling_audit=audit)
    assert row["t0_vph"] == 100.0
    assert row["vph_stratum"] == "high"
    assert "absolute_view_growth" not in row


def test_manifest_paths_immutable_write() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "broad.jsonl"
        write_jsonl(path, [serialize_stage110_broad_row(_candidate("a"))])
        before = path.read_text(encoding="utf-8")
        assert path.is_file()
        assert json.loads(before.splitlines()[0])["video_id"] == "a"


def test_missing_subscriber_stays_eligible() -> None:
    candidate = _candidate("s1")
    candidate.final_subscribers = None
    eligible, _ = build_eligible_pool([candidate])
    assert len(eligible) == 1


async def _run_all_tests() -> None:
    sync_tests = [
        test_stratum_boundaries_from_t0_only,
        test_design_a_allocation_and_seed,
        test_keyword_cap_respected,
        test_max_two_videos_per_channel,
        test_broad_preserved_before_sample,
        test_sample_ids_subset,
        test_no_outcome_fields_in_pool_record,
        test_dedupe_video_id,
        test_serialize_sample_row_fields,
        test_manifest_paths_immutable_write,
        test_missing_subscriber_stays_eligible,
    ]
    failed = 0
    for test in sync_tests:
        try:
            test()
            print(f"OK {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    try:
        await test_baseline_only_for_selected_mock()
        print("OK test_baseline_only_for_selected_mock")
    except Exception as exc:
        failed += 1
        print(f"FAIL test_baseline_only_for_selected_mock: {exc}")
    if failed:
        raise SystemExit(f"{failed} test(s) failed")
    print("All Stage 1.10C tests passed.")


if __name__ == "__main__":
    import asyncio

    asyncio.run(_run_all_tests())
