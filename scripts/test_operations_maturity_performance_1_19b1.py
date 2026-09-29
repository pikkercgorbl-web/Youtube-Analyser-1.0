"""Parity and edge-case tests for SQL maturity path (Stage 1.19B1)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import Channel, KeywordDiscoveryHit, TargetKeyword, Video, VideoFormat, VideoSnapshot
from app.services.operations_maturity_sql import compute_maturity_aggregate_sql
from app.services.operations_overview_service import compute_keyword_outcome_maturity_legacy

UTC = timezone.utc
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _session():
    return sessionmaker(bind=_engine())()


def _seed_video(session, video_id: str = "vid1") -> None:
    if session.get(Channel, "ch") is None:
        session.add(Channel(id="ch", title="C", subscribers_count=1, created_at=NOW))
        session.flush()
    if session.get(Video, video_id) is None:
        session.add(
            Video(
                id=video_id,
                channel_id="ch",
                title="T",
                published_at=NOW - timedelta(days=3),
                content_format=VideoFormat.UNKNOWN,
            ),
        )
        session.flush()


def _parity(session, *, mode: str = "all_hits", now: datetime = NOW) -> None:
    legacy = compute_keyword_outcome_maturity_legacy(session, attribution_mode=mode, now=now)
    optimized = compute_maturity_aggregate_sql(session, attribution_mode=mode, now=now)
    fields = (
        "attributed_observation_count",
        "pending_72h_count",
        "matured_72h_count",
        "valid_72h_outcome_count",
        "missing_72h_outcome_count",
        "matures_next_6h",
        "matures_next_24h",
        "matures_next_48h",
    )
    for name in fields:
        assert getattr(legacy, name) == getattr(optimized, name), f"{name} {mode}"


def test_rescan_baseline_dedupe() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    _seed_video(session)
    disc = NOW - timedelta(hours=100)
    for run in ("r1", "r2"):
        session.add(
            KeywordDiscoveryHit(
                keyword_id=kw.id,
                video_id="vid1",
                discovery_run_id=run,
                discovered_at=disc if run == "r1" else disc + timedelta(hours=1),
                views_at_discovery=100,
            ),
        )
    session.commit()
    _parity(session)
    row = compute_maturity_aggregate_sql(session, now=NOW)
    assert row.attributed_observation_count == 1
    assert row.matured_72h_count == 1


def test_same_timestamp_tie_lowest_id_wins_all_hits() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    _seed_video(session)
    ts = NOW - timedelta(hours=100)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="vid1",
            discovery_run_id="r1",
            discovered_at=ts,
            views_at_discovery=10,
        ),
    )
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="vid1",
            discovery_run_id="r2",
            discovered_at=ts,
            views_at_discovery=999,
        ),
    )
    session.commit()
    _parity(session)


def test_pending_count() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    _seed_video(session)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="vid1",
            discovery_run_id="r1",
            discovered_at=NOW - timedelta(hours=10),
            views_at_discovery=1,
        ),
    )
    session.commit()
    row = compute_maturity_aggregate_sql(session, now=NOW)
    assert row.pending_72h_count == 1
    assert row.matured_72h_count == 0


def test_matured_valid_and_missing() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    _seed_video(session, "v_ok")
    _seed_video(session, "v_miss")
    maturity = NOW - timedelta(hours=1)
    disc = maturity - timedelta(hours=72)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v_ok",
            discovery_run_id="r1",
            discovered_at=disc,
            views_at_discovery=50,
        ),
    )
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v_miss",
            discovery_run_id="r1",
            discovered_at=disc,
            views_at_discovery=50,
        ),
    )
    session.add(
        VideoSnapshot(
            video_id="v_ok",
            channel_id="ch",
            captured_at=maturity,
            views=200,
            source="test",
            run_id="snap1",
        ),
    )
    session.commit()
    _parity(session)
    row = compute_maturity_aggregate_sql(session, now=NOW)
    assert row.valid_72h_outcome_count == 1
    assert row.missing_72h_outcome_count == 1


def test_snapshot_at_minus_12h_accepted() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    _seed_video(session)
    maturity = NOW - timedelta(hours=2)
    disc = maturity - timedelta(hours=72)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="vid1",
            discovery_run_id="r1",
            discovered_at=disc,
            views_at_discovery=1,
        ),
    )
    session.add(
        VideoSnapshot(
            video_id="vid1",
            channel_id="ch",
            captured_at=maturity - timedelta(hours=12),
            views=10,
            source="test",
            run_id="s1",
        ),
    )
    session.commit()
    assert compute_maturity_aggregate_sql(session, now=NOW).valid_72h_outcome_count == 1


def test_snapshot_at_plus_12h_accepted() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    _seed_video(session)
    maturity = NOW - timedelta(hours=2)
    disc = maturity - timedelta(hours=72)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="vid1",
            discovery_run_id="r1",
            discovered_at=disc,
            views_at_discovery=1,
        ),
    )
    session.add(
        VideoSnapshot(
            video_id="vid1",
            channel_id="ch",
            captured_at=maturity + timedelta(hours=12),
            views=10,
            source="test",
            run_id="s1",
        ),
    )
    session.commit()
    assert compute_maturity_aggregate_sql(session, now=NOW).valid_72h_outcome_count == 1


def test_outside_tolerance_rejected() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    _seed_video(session)
    maturity = NOW - timedelta(hours=2)
    disc = maturity - timedelta(hours=72)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="vid1",
            discovery_run_id="r1",
            discovered_at=disc,
            views_at_discovery=1,
        ),
    )
    session.add(
        VideoSnapshot(
            video_id="vid1",
            channel_id="ch",
            captured_at=maturity + timedelta(hours=12, seconds=1),
            views=10,
            source="test",
            run_id="s1",
        ),
    )
    session.commit()
    row = compute_maturity_aggregate_sql(session, now=NOW)
    assert row.valid_72h_outcome_count == 0
    assert row.missing_72h_outcome_count == 1


def test_nearest_snapshot_chosen() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    _seed_video(session)
    maturity = NOW - timedelta(hours=2)
    disc = maturity - timedelta(hours=72)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="vid1",
            discovery_run_id="r1",
            discovered_at=disc,
            views_at_discovery=1,
        ),
    )
    session.add(
        VideoSnapshot(
            video_id="vid1",
            channel_id="ch",
            captured_at=maturity + timedelta(hours=10),
            views=10,
            source="test",
            run_id="far",
        ),
    )
    session.add(
        VideoSnapshot(
            video_id="vid1",
            channel_id="ch",
            captured_at=maturity + timedelta(hours=1),
            views=20,
            source="test",
            run_id="near",
        ),
    )
    session.commit()
    assert compute_maturity_aggregate_sql(session, now=NOW).valid_72h_outcome_count == 1


def test_first_discovery_tie_lowest_keyword_id() -> None:
    session = _session()
    k1 = TargetKeyword(keyword="k1")
    k2 = TargetKeyword(keyword="k2")
    session.add_all([k1, k2])
    session.flush()
    _seed_video(session)
    ts = NOW - timedelta(hours=100)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=k2.id,
            video_id="vid1",
            discovery_run_id="r1",
            discovered_at=ts,
            views_at_discovery=1,
        ),
    )
    session.add(
        KeywordDiscoveryHit(
            keyword_id=k1.id,
            video_id="vid1",
            discovery_run_id="r2",
            discovered_at=ts,
            views_at_discovery=2,
        ),
    )
    session.commit()
    _parity(session, mode="first_discovery")
    row = compute_maturity_aggregate_sql(session, attribution_mode="first_discovery", now=NOW)
    assert row.attributed_observation_count == 1


def test_upcoming_windows_pending_only() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    _seed_video(session, "v6")
    _seed_video(session, "v30")
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v6",
            discovery_run_id="r1",
            discovered_at=NOW - timedelta(hours=72 - 3),
            views_at_discovery=1,
        ),
    )
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v30",
            discovery_run_id="r1",
            discovered_at=NOW - timedelta(hours=72 - 20),
            views_at_discovery=1,
        ),
    )
    session.commit()
    _parity(session)
    row = compute_maturity_aggregate_sql(session, now=NOW)
    assert row.matures_next_6h == 1
    assert row.matures_next_24h == 2


def test_null_views_at_discovery_not_in_valid_missing() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    _seed_video(session)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="vid1",
            discovery_run_id="r1",
            discovered_at=NOW - timedelta(hours=100),
            views_at_discovery=None,
        ),
    )
    session.commit()
    _parity(session)
    row = compute_maturity_aggregate_sql(session, now=NOW)
    assert row.matured_72h_count == 1
    assert row.valid_72h_outcome_count == 0
    assert row.missing_72h_outcome_count == 0


def test_optimized_matches_legacy_reference() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    _seed_video(session)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="vid1",
            discovery_run_id="r1",
            discovered_at=NOW - timedelta(hours=50),
            views_at_discovery=5,
        ),
    )
    session.commit()
    _parity(session, mode="all_hits")
    _parity(session, mode="first_discovery")


def test_no_per_baseline_sql_growth() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    for idx in range(5):
        vid = f"v{idx}"
        _seed_video(session, vid)
        session.add(
            KeywordDiscoveryHit(
                keyword_id=kw.id,
                video_id=vid,
                discovery_run_id=f"r{idx}",
                discovered_at=NOW - timedelta(hours=100),
                views_at_discovery=1,
            ),
        )
    session.commit()
    engine = session.get_bind()
    count = 0

    def before_cursor_execute(*_a, **_k) -> None:
        nonlocal count
        count += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute, retval=False)
    try:
        compute_maturity_aggregate_sql(session, now=NOW)
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    assert count == 1


def main() -> None:
    tests = [
        test_rescan_baseline_dedupe,
        test_same_timestamp_tie_lowest_id_wins_all_hits,
        test_pending_count,
        test_matured_valid_and_missing,
        test_snapshot_at_minus_12h_accepted,
        test_snapshot_at_plus_12h_accepted,
        test_outside_tolerance_rejected,
        test_nearest_snapshot_chosen,
        test_first_discovery_tie_lowest_keyword_id,
        test_upcoming_windows_pending_only,
        test_null_views_at_discovery_not_in_valid_missing,
        test_optimized_matches_legacy_reference,
        test_no_per_baseline_sql_growth,
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
        raise SystemExit(f"{failed} failed")
    print("All maturity performance tests passed.")


if __name__ == "__main__":
    main()
