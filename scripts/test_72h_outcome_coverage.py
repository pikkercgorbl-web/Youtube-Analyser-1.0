"""Stage 1.20E.1 — 72h outcome coverage semantics and diagnostics."""

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
from app.models.orm import KeywordDiscoveryHit, KeywordScanRun, TargetKeyword, VideoSnapshot
from app.services.keyword_evidence_service import get_keyword_evidence, list_keyword_evidence
from app.services.keyword_lifecycle_calibration_service import build_calibration_report
from app.services.keyword_performance_evaluation import (
    HORIZON_SNAPSHOT_TOLERANCE_HOURS,
    KeywordVideoBaseline,
    compute_horizon_coverage_diagnostics,
    match_horizon_outcome,
    tally_delayed_outcomes_for_videos,
)
from app.services.operations_maturity_sql import compute_maturity_aggregate_sql

UTC = timezone.utc
NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _scan(session, kw: TargetKeyword) -> None:
    session.add(
        KeywordScanRun(
            keyword_id=kw.id,
            discovery_run_id="r1",
            started_at=NOW,
            finished_at=NOW,
            status="ok",
            raw_candidates=1,
            persisted_videos=1,
        ),
    )


def test_pending_not_counted_as_missing() -> None:
    session = _session()
    kw = TargetKeyword(keyword="pending", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    _scan(session, kw)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v_pending",
            discovery_run_id="run_1",
            discovered_at=NOW - timedelta(hours=24),
            views_at_discovery=10,
            vph_at_discovery=1.0,
            content_format="regular",
            qualification_state="passed",
        ),
    )
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v_mature",
            discovery_run_id="run_1",
            discovered_at=NOW - timedelta(days=5),
            views_at_discovery=10,
            vph_at_discovery=1.0,
            content_format="regular",
            qualification_state="passed",
        ),
    )
    session.commit()
    ev = get_keyword_evidence(session, kw.id, include_breakout=False, include_delayed=True, evaluated_at=NOW)
    assert ev is not None
    d = ev.delayed_outcome
    assert d.attributed_observation_count == 2
    assert d.matured_72h_count == 1
    assert d.valid_72h_outcome_count == 0
    assert d.missing_72h_outcome_count == 1
    assert d.matured_72h_count == d.valid_72h_outcome_count + d.missing_72h_outcome_count


def test_matured_valid_snapshot() -> None:
    session = _session()
    kw = TargetKeyword(keyword="valid", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    _scan(session, kw)
    discovery = NOW - timedelta(days=5)
    target = discovery + timedelta(hours=72)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v1",
            discovery_run_id="run_1",
            discovered_at=discovery,
            views_at_discovery=100,
            vph_at_discovery=1.0,
            content_format="regular",
            qualification_state="passed",
        ),
    )
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch",
            captured_at=target,
            published_at=discovery,
            age_hours=72.0,
            views=500,
            source="t",
            run_id="r",
        ),
    )
    session.commit()
    ev = get_keyword_evidence(session, kw.id, include_breakout=False, include_delayed=True, evaluated_at=NOW)
    assert ev is not None
    assert ev.delayed_outcome.valid_72h_outcome_count == 1
    assert ev.delayed_outcome.missing_72h_outcome_count == 0


def test_matured_no_snapshot_missing() -> None:
    session = _session()
    kw = TargetKeyword(keyword="nosnap", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    _scan(session, kw)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v1",
            discovery_run_id="run_1",
            discovered_at=NOW - timedelta(days=5),
            views_at_discovery=100,
            vph_at_discovery=1.0,
            content_format="regular",
            qualification_state="passed",
        ),
    )
    session.commit()
    ev = get_keyword_evidence(session, kw.id, include_breakout=False, include_delayed=True, evaluated_at=NOW)
    assert ev.delayed_outcome.matured_72h_count == 1
    assert ev.delayed_outcome.valid_72h_outcome_count == 0
    assert ev.delayed_outcome.missing_72h_outcome_count == 1


def test_outside_tolerance_missing() -> None:
    session = _session()
    kw = TargetKeyword(keyword="outside", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    _scan(session, kw)
    discovery = NOW - timedelta(days=5)
    target = discovery + timedelta(hours=72)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v1",
            discovery_run_id="run_1",
            discovered_at=discovery,
            views_at_discovery=100,
            vph_at_discovery=1.0,
            content_format="regular",
            qualification_state="passed",
        ),
    )
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch",
            captured_at=target + timedelta(hours=HORIZON_SNAPSHOT_TOLERANCE_HOURS + 1),
            published_at=discovery,
            age_hours=85.0,
            views=500,
            source="t",
            run_id="r",
        ),
    )
    session.commit()
    ev = get_keyword_evidence(session, kw.id, include_breakout=False, include_delayed=True, evaluated_at=NOW)
    assert ev.delayed_outcome.valid_72h_outcome_count == 0
    assert ev.delayed_outcome.missing_72h_outcome_count == 1


def test_nearest_inside_tolerance_selected() -> None:
    discovery = NOW - timedelta(days=5)
    target = discovery + timedelta(hours=72)
    far = VideoSnapshot(
        video_id="v1",
        channel_id="ch",
        captured_at=target + timedelta(hours=10),
        published_at=discovery,
        age_hours=82.0,
        views=900,
        source="t",
        run_id="r1",
    )
    near = VideoSnapshot(
        video_id="v1",
        channel_id="ch",
        captured_at=target + timedelta(hours=1),
        published_at=discovery,
        age_hours=73.0,
        views=500,
        source="t",
        run_id="r2",
    )
    baseline = KeywordVideoBaseline(
        keyword_id=1,
        video_id="v1",
        discovery_at=discovery,
        views_at_discovery=100,
        vph_at_discovery=1.0,
    )
    outcome = match_horizon_outcome(baseline, {"v1": [far, near]})
    assert outcome is not None
    assert outcome.outcome_views == 500


def test_sql_matured_equals_valid_plus_missing() -> None:
    session = _session()
    kw = TargetKeyword(keyword="sql", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    disc_old = NOW - timedelta(days=5)
    disc_new = NOW - timedelta(hours=12)
    session.add_all(
        [
            KeywordDiscoveryHit(
                keyword_id=kw.id,
                video_id="a",
                discovery_run_id="r",
                discovered_at=disc_old,
                views_at_discovery=1,
            ),
            KeywordDiscoveryHit(
                keyword_id=kw.id,
                video_id="b",
                discovery_run_id="r",
                discovered_at=disc_new,
                views_at_discovery=1,
            ),
        ],
    )
    session.commit()
    row = compute_maturity_aggregate_sql(session, now=NOW)
    assert row.matured_72h_count == row.valid_72h_outcome_count + row.missing_72h_outcome_count


def test_first_discovery_timestamp_preserved() -> None:
    session = _session()
    kw = TargetKeyword(keyword="first", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    _scan(session, kw)
    t0 = NOW - timedelta(days=10)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v1",
            discovery_run_id="run_1",
            discovered_at=t0,
            views_at_discovery=50,
            vph_at_discovery=1.0,
            content_format="regular",
            qualification_state="passed",
        ),
    )
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch",
            captured_at=t0 + timedelta(hours=72),
            published_at=t0,
            age_hours=72.0,
            views=200,
            source="t",
            run_id="r",
        ),
    )
    session.commit()
    ev = list_keyword_evidence(
        session,
        attribution_mode="first_discovery",
        include_breakout=False,
        include_delayed=True,
        limit=10,
        evaluated_at=NOW,
    )
    item = next(i for i in ev.items if i.keyword_id == kw.id)
    assert item.delayed_outcome.valid_72h_outcome_count == 1


def test_all_hits_uses_per_keyword_video_baseline() -> None:
    session = _session()
    kw = TargetKeyword(keyword="allhits", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    _scan(session, kw)
    t_late = NOW - timedelta(days=4)
    t_early = NOW - timedelta(days=6)
    session.add_all(
        [
            KeywordDiscoveryHit(
                keyword_id=kw.id,
                video_id="v1",
                discovery_run_id="run_a",
                discovered_at=t_early,
                views_at_discovery=10,
                vph_at_discovery=1.0,
                content_format="regular",
                qualification_state="passed",
            ),
            KeywordDiscoveryHit(
                keyword_id=kw.id,
                video_id="v1",
                discovery_run_id="run_b",
                discovered_at=t_late,
                views_at_discovery=10,
                vph_at_discovery=1.0,
                content_format="regular",
                qualification_state="passed",
            ),
        ],
    )
    target = t_early + timedelta(hours=72)
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch",
            captured_at=target,
            published_at=t_early,
            age_hours=72.0,
            views=100,
            source="t",
            run_id="r",
        ),
    )
    session.commit()
    ev = get_keyword_evidence(
        session,
        kw.id,
        attribution_mode="all_hits",
        include_breakout=False,
        include_delayed=True,
        evaluated_at=NOW,
    )
    assert ev.delayed_outcome.valid_72h_outcome_count == 1


def test_timezone_aware_discovery_and_snapshot() -> None:
    session = _session()
    kw = TargetKeyword(keyword="tz", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    _scan(session, kw)
    discovery = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v1",
            discovery_run_id="run_1",
            discovered_at=discovery,
            views_at_discovery=1,
            vph_at_discovery=1.0,
            content_format="regular",
            qualification_state="passed",
        ),
    )
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch",
            captured_at=discovery + timedelta(hours=72),
            published_at=discovery,
            age_hours=72.0,
            views=2,
            source="t",
            run_id="r",
        ),
    )
    session.commit()
    ref = discovery + timedelta(hours=80)
    ev = get_keyword_evidence(session, kw.id, include_breakout=False, include_delayed=True, evaluated_at=ref)
    assert ev.delayed_outcome.valid_72h_outcome_count == 1


def test_case_review_excludes_zero_valid_keywords() -> None:
    session = _session()
    for label in ("z", "y"):
        kw = TargetKeyword(keyword=label, lifecycle_status="active", source_type="seed")
        session.add(kw)
        session.flush()
        _scan(session, kw)
        session.add(
            KeywordDiscoveryHit(
                keyword_id=kw.id,
                video_id=f"v_{label}",
                discovery_run_id="run_1",
                discovered_at=NOW - timedelta(days=5),
                views_at_discovery=1,
                vph_at_discovery=1.0,
                content_format="regular",
                qualification_state="passed",
            ),
        )
    session.commit()
    report = build_calibration_report(session, include_breakout=False, include_delayed=True, limit=10, now=NOW)
    assert report.case_review["valid_72h_outcomes"] == []


def test_diagnostics_no_snapshot_vs_outside_window() -> None:
    session = _session()
    kw = TargetKeyword(keyword="diag", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    discovery = NOW - timedelta(days=5)
    session.add_all(
        [
            KeywordDiscoveryHit(
                keyword_id=kw.id,
                video_id="none",
                discovery_run_id="r",
                discovered_at=discovery,
                views_at_discovery=1,
            ),
            KeywordDiscoveryHit(
                keyword_id=kw.id,
                video_id="out",
                discovery_run_id="r",
                discovered_at=discovery,
                views_at_discovery=1,
            ),
        ],
    )
    target = discovery + timedelta(hours=72)
    session.add(
        VideoSnapshot(
            video_id="out",
            channel_id="ch",
            captured_at=target + timedelta(hours=30),
            published_at=discovery,
            age_hours=102.0,
            views=5,
            source="t",
            run_id="r",
        ),
    )
    session.commit()
    diag = compute_horizon_coverage_diagnostics(session, now=NOW, keyword_ids=[kw.id])
    assert diag.matured_72h_count == 2
    assert diag.matured_with_no_snapshot == 1
    assert diag.matured_with_only_outside_window == 1
    assert diag.valid_72h_outcome_count == 0


def test_tally_helper_invariant() -> None:
    baselines = {
        (1, "a"): KeywordDiscoveryHit(
            keyword_id=1,
            video_id="a",
            discovery_run_id="r",
            discovered_at=NOW - timedelta(days=1),
            views_at_discovery=1,
        ),
        (1, "b"): KeywordDiscoveryHit(
            keyword_id=1,
            video_id="b",
            discovery_run_id="r",
            discovered_at=NOW - timedelta(days=5),
            views_at_discovery=1,
        ),
    }
    tally, _ = tally_delayed_outcomes_for_videos(
        {"a", "b"},
        baselines,
        1,
        reference=NOW,
        horizon_hours=72,
        snapshots_by_video={},
    )
    assert tally.matured == tally.valid + tally.missing
    assert tally.pending == 1


def main() -> None:
    tests = [
        test_pending_not_counted_as_missing,
        test_matured_valid_snapshot,
        test_matured_no_snapshot_missing,
        test_outside_tolerance_missing,
        test_nearest_inside_tolerance_selected,
        test_sql_matured_equals_valid_plus_missing,
        test_first_discovery_timestamp_preserved,
        test_all_hits_uses_per_keyword_video_baseline,
        test_timezone_aware_discovery_and_snapshot,
        test_case_review_excludes_zero_valid_keywords,
        test_diagnostics_no_snapshot_vs_outside_window,
        test_tally_helper_invariant,
    ]
    for fn in tests:
        fn()
        print(f"OK {fn.__name__}")
    print(f"All {len(tests)} tests passed.")


if __name__ == "__main__":
    main()
