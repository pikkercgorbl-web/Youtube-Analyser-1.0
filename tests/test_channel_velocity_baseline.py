"""Tests for age-aligned channel velocity baseline (Stage 1.12A)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.services.channel_velocity_baseline import (
    ChannelVelocityBaselineCandidateInput,
    ChannelVelocityBaselineConfig,
    SnapshotRecord,
    compute_age_window,
    compute_channel_velocity_baseline,
    compute_channel_velocity_baseline_from_snapshots,
    compute_channel_velocity_baselines,
    empirical_percentile_rank,
    select_nearest_snapshot_for_video,
)
from app.services.video_snapshot_storage import VideoSnapshotObservation, persist_video_snapshots


UTC = timezone.utc
T0 = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)
PUB = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)


def _snap(
    video_id: str,
    *,
    age: float,
    vph: float,
    published_at: datetime | None = PUB,
    captured_at: datetime | None = None,
    channel_id: str = "ch1",
    is_short: bool | None = None,
    is_live: bool | None = None,
    content_format: str | None = "regular",
) -> SnapshotRecord:
    if captured_at is None:
        captured_at = PUB + timedelta(hours=age)
    return SnapshotRecord(
        video_id=video_id,
        channel_id=channel_id,
        captured_at=captured_at,
        published_at=published_at,
        age_hours=age,
        vph=vph,
        content_format=content_format,
        is_short=is_short,
        is_live=is_live,
    )


def _compute(**kwargs: object):
    defaults = {
        "channel_id": "ch1",
        "candidate_video_id": "cand",
        "candidate_age_hours": 12.0,
        "candidate_vph": 3000.0,
        "candidate_published_at": datetime(2026, 9, 15, 8, 0, tzinfo=UTC),
        "candidate_captured_at": datetime(2026, 9, 15, 20, 0, tzinfo=UTC),
        "channel_snapshots": [],
    }
    defaults.update(kwargs)
    return compute_channel_velocity_baseline_from_snapshots(**defaults)  # type: ignore[arg-type]


def test_candidate_excluded() -> None:
    snaps = [_snap("cand", age=12, vph=999), _snap("h1", age=12, vph=500)]
    result = _compute(channel_snapshots=snaps)
    assert result.comparable_video_count == 1
    assert result.median_vph == 500.0


def test_only_videos_before_candidate_publication() -> None:
    candidate_pub = datetime(2026, 9, 15, 8, 0, tzinfo=UTC)
    old_pub = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
    future_pub = datetime(2026, 9, 16, 8, 0, tzinfo=UTC)
    snaps = [
        _snap(
            "h-old",
            age=12,
            vph=400,
            published_at=old_pub,
            captured_at=old_pub + timedelta(hours=12),
        ),
        _snap(
            "h-future",
            age=12,
            vph=9000,
            published_at=future_pub,
            captured_at=future_pub + timedelta(hours=12),
        ),
    ]
    result = _compute(
        channel_snapshots=snaps,
        candidate_published_at=candidate_pub,
    )
    assert result.comparable_video_count == 1
    assert result.median_vph == 400.0
    assert result.exclusion_counts.get("future_publication") == 1


def test_one_nearest_snapshot_per_video() -> None:
    snaps = [
        _snap("h1", age=10, vph=100),
        _snap("h1", age=12, vph=500, captured_at=PUB + timedelta(hours=12)),
        _snap("h1", age=14, vph=900),
    ]
    chosen = select_nearest_snapshot_for_video(snaps, 12.0)
    assert chosen is not None
    assert chosen.vph == 500.0


def test_multiple_snapshots_do_not_overweight() -> None:
    snaps = [
        _snap("h1", age=11, vph=100),
        _snap("h1", age=12, vph=500),
        _snap("h1", age=13, vph=100),
        _snap("h2", age=12, vph=600),
    ]
    result = _compute(channel_snapshots=snaps, candidate_vph=3000.0)
    assert result.comparable_video_count == 2
    assert result.median_vph == 550.0


def test_exact_age_match() -> None:
    snaps = [_snap("h1", age=12, vph=777)]
    result = _compute(channel_snapshots=snaps, candidate_age_hours=12.0)
    assert result.comparable_video_count == 1
    assert result.median_vph == 777.0


def test_age_window_inclusive_boundaries() -> None:
    tol, lo, hi = compute_age_window(12.0, ChannelVelocityBaselineConfig())
    assert tol == 3.0
    assert lo == 9.0
    assert hi == 15.0
    snaps = [
        _snap("lo", age=9, vph=100),
        _snap("hi", age=15, vph=200),
        _snap("out", age=8.99, vph=999),
    ]
    result = _compute(channel_snapshots=snaps)
    assert result.comparable_video_count == 2


def test_short_excluded() -> None:
    snaps = [_snap("s", age=12, vph=1, is_short=True)]
    result = _compute(channel_snapshots=snaps)
    assert result.comparable_video_count == 0
    assert result.exclusion_counts.get("short") == 1


def test_live_excluded() -> None:
    snaps = [_snap("l", age=12, vph=1, is_live=True)]
    result = _compute(channel_snapshots=snaps)
    assert result.exclusion_counts.get("live") == 1


def test_missing_vph_excluded() -> None:
    snaps = [
        SnapshotRecord("h1", "ch1", T0, PUB, 12.0, None),
    ]
    result = _compute(channel_snapshots=snaps)
    assert result.exclusion_counts.get("missing_vph") == 1


def test_invalid_age_excluded() -> None:
    snaps = [_snap("h1", age=0, vph=10)]
    result = _compute(channel_snapshots=snaps)
    assert result.exclusion_counts.get("invalid_age_hours") == 1


def test_zero_comparable_unavailable() -> None:
    result = _compute(channel_snapshots=[])
    assert result.baseline_status == "unavailable"
    assert result.median_vph is None


def test_insufficient_history_tier() -> None:
    snaps = [_snap(f"h{i}", age=12, vph=100 + i) for i in range(4)]
    result = _compute(channel_snapshots=snaps)
    assert result.baseline_status == "insufficient_history"
    assert result.median_vph is not None
    assert result.vph_vs_channel_median is None


def test_partial_tier() -> None:
    snaps = [_snap(f"h{i}", age=12, vph=100 + i) for i in range(7)]
    result = _compute(channel_snapshots=snaps, candidate_vph=1000.0)
    assert result.baseline_status == "partial"
    assert result.vph_vs_channel_median is not None


def test_ok_tier() -> None:
    snaps = [_snap(f"h{i}", age=12, vph=400 + i * 10) for i in range(10)]
    result = _compute(channel_snapshots=snaps, candidate_vph=3000.0)
    assert result.baseline_status == "ok"


def test_median_p75_p90() -> None:
    vphs = [400, 450, 500, 600, 700, 800, 900, 1000, 1100, 1200]
    hist_pub = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    snaps = [
        _snap(
            f"h{i}",
            age=12,
            vph=v,
            published_at=hist_pub,
            captured_at=hist_pub + timedelta(hours=12),
        )
        for i, v in enumerate(vphs)
    ]
    result = _compute(channel_snapshots=snaps)
    assert result.median_vph == 750.0
    assert result.p75_vph == 975.0
    assert result.p90_vph == 1110.0


def test_ratio_vs_median() -> None:
    snaps = [_snap(f"h{i}", age=12, vph=500) for i in range(10)]
    result = _compute(channel_snapshots=snaps, candidate_vph=3000.0)
    assert result.vph_vs_channel_median == 6.0


def test_zero_median_ratio_null() -> None:
    snaps = [_snap(f"h{i}", age=12, vph=0) for i in range(10)]
    result = _compute(channel_snapshots=snaps, candidate_vph=100.0)
    assert result.median_vph == 0.0
    assert result.vph_vs_channel_median is None


def test_percentile_rank() -> None:
    population = [400.0, 450.0, 500.0, 600.0, 700.0]
    assert empirical_percentile_rank(700.0, population) == 1.0
    assert empirical_percentile_rank(400.0, population) == 0.2


def test_future_leakage_with_capture_cutoff() -> None:
    candidate_cap = datetime(2026, 9, 15, 20, 0, tzinfo=UTC)
    future_pub = datetime(2026, 9, 15, 21, 0, tzinfo=UTC)
    snaps = [
        _snap(
            "h1",
            age=12,
            vph=500,
            published_at=future_pub,
            captured_at=future_pub + timedelta(hours=12),
        ),
    ]
    result = _compute(
        channel_snapshots=snaps,
        candidate_published_at=None,
        candidate_captured_at=candidate_cap,
    )
    assert result.comparable_video_count == 0
    assert result.exclusion_counts.get("future_publication") == 1


def test_tie_break_earlier_captured_at() -> None:
    snaps = [
        _snap("h1", age=11, vph=100, captured_at=datetime(2026, 9, 14, 20, 0, tzinfo=UTC)),
        _snap("h1", age=13, vph=200, captured_at=datetime(2026, 9, 14, 21, 0, tzinfo=UTC)),
    ]
    chosen = select_nearest_snapshot_for_video(snaps, 12.0)
    assert chosen is not None
    assert chosen.vph == 100.0


def test_batch_matches_single() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    published = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    observations = []
    for index in range(10):
        captured = published + timedelta(hours=12)
        vph = 400.0 + index * 10
        observations.append(
            VideoSnapshotObservation(
                video_id=f"h{index}",
                channel_id="ch1",
                captured_at=captured,
                published_at=published,
                source="test",
                run_id=f"r{index}",
                views=int(vph * 12),
                content_format="regular",
            ),
        )
    persist_video_snapshots(session, observations)
    session.commit()

    single = compute_channel_velocity_baseline(
        session,
        channel_id="ch1",
        candidate_video_id="cand",
        candidate_age_hours=12.0,
        candidate_vph=3000.0,
        candidate_published_at=datetime(2026, 9, 15, 8, 0, tzinfo=UTC),
    )
    batch = compute_channel_velocity_baselines(
        session,
        [
            ChannelVelocityBaselineCandidateInput(
                channel_id="ch1",
                candidate_video_id="cand",
                candidate_age_hours=12.0,
                candidate_vph=3000.0,
                candidate_published_at=datetime(2026, 9, 15, 8, 0, tzinfo=UTC),
            ),
        ],
    )[0]
    assert batch.baseline_status == single.baseline_status
    assert batch.median_vph == single.median_vph
    assert batch.vph_vs_channel_median == single.vph_vs_channel_median


def main() -> None:
    tests = [
        test_candidate_excluded,
        test_only_videos_before_candidate_publication,
        test_one_nearest_snapshot_per_video,
        test_multiple_snapshots_do_not_overweight,
        test_exact_age_match,
        test_age_window_inclusive_boundaries,
        test_short_excluded,
        test_live_excluded,
        test_missing_vph_excluded,
        test_invalid_age_excluded,
        test_zero_comparable_unavailable,
        test_insufficient_history_tier,
        test_partial_tier,
        test_ok_tier,
        test_median_p75_p90,
        test_ratio_vs_median,
        test_zero_median_ratio_null,
        test_percentile_rank,
        test_future_leakage_with_capture_cutoff,
        test_tie_break_earlier_captured_at,
        test_batch_matches_single,
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
    print("All channel velocity baseline tests passed.")


if __name__ == "__main__":
    main()
