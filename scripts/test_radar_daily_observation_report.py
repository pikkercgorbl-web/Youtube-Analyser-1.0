"""Tests for read-only Radar daily observation report."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest.mock as mock
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import (
    AttentionRun,
    KeywordDiscoveryHit,
    KeywordScanRun,
    MonitoringCycleRun,
    TargetKeyword,
    VideoSnapshot,
)
from app.services.radar_daily_observation_report import (
    T_EVENT,
    T_NOW,
    RadarDailyReportError,
    build_radar_daily_observation_report,
    compute_day_over_day,
    metric_value,
    render_radar_daily_observation_markdown,
    utc_day_window,
)
from app.services.radar_daily_observation_storage import (
    build_observation_index_last_n_days,
    complete_utc_days_for_catchup,
    missing_original_days,
    original_json_path,
    persist_daily_observation_artifacts,
)

UTC = timezone.utc


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _session():
    return sessionmaker(bind=_engine())()


def test_utc_day_window_boundaries() -> None:
    w = utc_day_window(datetime(2026, 10, 8, tzinfo=UTC).date(), reference_now=datetime(2026, 10, 8, 15, 0, tzinfo=UTC))
    assert w.window_start == datetime(2026, 10, 8, 0, 0, tzinfo=UTC)
    assert w.window_end == datetime(2026, 10, 9, 0, 0, tzinfo=UTC)
    assert w.day_complete is False

    w2 = utc_day_window(datetime(2026, 10, 7, tzinfo=UTC).date(), reference_now=datetime(2026, 10, 9, 0, 0, tzinfo=UTC))
    assert w2.day_complete is True


def test_hit_at_window_end_excluded() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k1", lifecycle_status="active")
    session.add(kw)
    session.flush()
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="vid1",
            discovery_run_id="d1",
            discovered_at=datetime(2026, 10, 9, 0, 0, tzinfo=UTC),
            video_existed_before_discovery=False,
        ),
    )
    session.commit()
    report = build_radar_daily_observation_report(
        session,
        utc_day=datetime(2026, 10, 8, tzinfo=UTC).date(),
        generated_at=datetime(2026, 10, 10, tzinfo=UTC),
    )
    assert metric_value(report["discovery"]["discovery_hits_in_window"]) == 0
    assert report["discovery"]["discovery_hits_in_window"]["temporal_semantics"] == T_EVENT


def test_original_immutable_and_revision() -> None:
    session = _session()
    day = datetime(2026, 10, 8, tzinfo=UTC).date()
    report = build_radar_daily_observation_report(
        session,
        utc_day=day,
        generated_at=datetime(2026, 10, 9, tzinfo=UTC),
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        o1, j1, _ = persist_daily_observation_artifacts(report, output_dir=out, as_revision=False)
        assert o1 == "created_original"
        report2 = dict(report)
        report2["generated_at_utc"] = "2026-10-10T00:00:00+00:00"
        report2["discovery"]["discovery_hits_in_window"]["value"] = 99
        o2, j2, _ = persist_daily_observation_artifacts(report2, output_dir=out, as_revision=False)
        assert o2 == "skipped_existing_original"
        assert j2 == j1
        saved = json.loads(j1.read_text(encoding="utf-8"))
        assert metric_value(saved["discovery"]["discovery_hits_in_window"]) != 99
        o3, j3, _ = persist_daily_observation_artifacts(report2, output_dir=out, as_revision=True)
        assert o3 == "created_revision"
        assert "revision" in j3.name
        rev = json.loads(j3.read_text(encoding="utf-8"))
        assert rev["artifact_record"]["kind"] == "revision"


def test_catch_up_missing_days() -> None:
    now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
    candidates = complete_utc_days_for_catchup(reference_now=now, max_days=3)
    assert candidates == [
        datetime(2026, 10, 9, tzinfo=UTC).date(),
        datetime(2026, 10, 10, tzinfo=UTC).date(),
        datetime(2026, 10, 11, tzinfo=UTC).date(),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        missing = missing_original_days(out, candidates)
        assert len(missing) == 3


def test_index_marks_missing_not_zero() -> None:
    now = datetime(2026, 10, 12, tzinfo=UTC)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        idx = build_observation_index_last_n_days(out, complete_day_count=2, reference_now=now)
        assert idx["originals_missing"] == 2
        assert all(r["status"] == "missing" for r in idx["days"])


def test_monitoring_missing_ratio_null_when_selected_zero() -> None:
    session = _session()
    session.add(
        MonitoringCycleRun(
            run_id="m0",
            started_at=datetime(2026, 10, 8, 12, 0, tzinfo=UTC),
            finished_at=datetime(2026, 10, 8, 12, 5, tzinfo=UTC),
            runtime_seconds=1.0,
            cycle_status="ok",
            selected_request_count=0,
            inserted_snapshot_count=0,
            missing_count=5,
        ),
    )
    session.commit()
    report = build_radar_daily_observation_report(
        session,
        utc_day=datetime(2026, 10, 8, tzinfo=UTC).date(),
        generated_at=datetime(2026, 10, 9, tzinfo=UTC),
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        persist_daily_observation_artifacts(report, output_dir=out)
        idx = build_observation_index_last_n_days(out, complete_day_count=14, reference_now=datetime(2026, 10, 9, tzinfo=UTC))
        row = next(r for r in idx["days"] if r.get("utc_day") == "2026-10-08")
        assert row["monitoring_missing_to_selected_ratio"] is None


def test_monitoring_quiet_pool_diagnostic() -> None:
    session = _session()
    session.add(
        MonitoringCycleRun(
            run_id="m1",
            started_at=datetime(2026, 10, 8, 12, 0, tzinfo=UTC),
            finished_at=datetime(2026, 10, 8, 12, 5, tzinfo=UTC),
            runtime_seconds=300.0,
            cycle_status="ok",
            loaded_video_count=100,
            eligible_video_count=10,
            due_count=0,
            overdue_count=0,
            selected_request_count=0,
            inserted_snapshot_count=0,
        ),
    )
    session.commit()
    report = build_radar_daily_observation_report(
        session,
        utc_day=datetime(2026, 10, 8, tzinfo=UTC).date(),
        generated_at=datetime(2026, 10, 9, tzinfo=UTC),
    )
    codes = {d["code"] for d in report["diagnostics_for_utc_day"]}
    assert "monitoring_quiet_pool" in codes


def test_monitoring_reconciliation_fields() -> None:
    session = _session()
    session.add(
        MonitoringCycleRun(
            run_id="m2",
            started_at=datetime(2026, 10, 8, 12, 0, tzinfo=UTC),
            finished_at=datetime(2026, 10, 8, 12, 5, tzinfo=UTC),
            runtime_seconds=300.0,
            cycle_status="partial",
            selected_request_count=5,
            inserted_snapshot_count=2,
            duplicate_snapshot_count=2,
            missing_count=1,
            fetch_failed_count=0,
        ),
    )
    session.commit()
    report = build_radar_daily_observation_report(
        session,
        utc_day=datetime(2026, 10, 8, tzinfo=UTC).date(),
        generated_at=datetime(2026, 10, 9, tzinfo=UTC),
    )
    recon = report["monitoring"]["selected_vs_inserted_reconciliation"]
    assert recon["selected_request_count_sum"] == 5
    assert recon["outcome_counts_from_cycle_summaries"]["duplicate_snapshot_count"] == 2


def test_read_models_split_day_end_vs_generation() -> None:
    session = _session()
    session.add(
        AttentionRun(
            run_id="att_old",
            computed_at=datetime(2026, 10, 8, 10, 0, tzinfo=UTC),
            timezone_name="UTC",
            window_hours=24,
            window_start=datetime(2026, 10, 7, 10, 0, tzinfo=UTC),
            window_end=datetime(2026, 10, 8, 10, 0, tzinfo=UTC),
        ),
    )
    session.commit()
    report = build_radar_daily_observation_report(
        session,
        utc_day=datetime(2026, 10, 8, tzinfo=UTC).date(),
        generated_at=datetime(2026, 10, 9, 12, 0, tzinfo=UTC),
    )
    att = report["read_models"]["attention"]
    assert att["publish_as_of_utc_day_end"]["run_id"] == "att_old"
    assert att["publish_as_of_utc_day_end"]["temporal_semantics"] == "state_at_utc_day_end"
    assert att["latest_in_database_at_generation"]["temporal_semantics"] == T_NOW


def test_day_over_day_skips_incomplete_current_day() -> None:
    cur = {"utc_day": "2026-10-09", "day_complete": False}
    prev = {"utc_day": "2026-10-08", "day_complete": True}
    dod = compute_day_over_day(cur, prev)
    assert dod["status"] == "skipped"
    assert dod["reason"] == "current_utc_day_incomplete"


def test_day_over_day_missing_previous_file() -> None:
    cur = {"utc_day": "2026-10-08", "day_complete": True}
    dod = compute_day_over_day(cur, None)
    assert dod["status"] == "skipped"
    assert dod["reason"] == "previous_utc_day_file_missing"


def test_optional_table_missing_not_zero() -> None:
    session = _session()
    session.execute(text("DROP TABLE IF EXISTS topic_exploration_passes"))
    session.commit()
    report = build_radar_daily_observation_report(
        session,
        utc_day=datetime(2026, 10, 8, tzinfo=UTC).date(),
        generated_at=datetime(2026, 10, 9, tzinfo=UTC),
    )
    ex = report["expansion_and_exploration"]["exploration"]
    assert ex["section_status"] == "unavailable"
    assert ex.get("pass_count") is None


def test_read_only_no_db_mutations() -> None:
    session = _session()
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="c1",
            captured_at=datetime(2026, 10, 8, 1, 0, tzinfo=UTC),
            published_at=datetime(2026, 10, 7, tzinfo=UTC),
            age_hours=24.0,
            views=100,
            source="monitoring_worker",
            run_id="r1",
            fetch_status="ok",
        ),
    )
    session.commit()
    counts_before = {
        t: session.scalar(select(func.count()).select_from(Base.metadata.tables[t]))
        for t in ("video_snapshots", "monitoring_cycle_runs", "keyword_scan_runs")
    }
    with mock.patch("socket.socket", side_effect=AssertionError("network forbidden")):
        build_radar_daily_observation_report(
            session,
            utc_day=datetime(2026, 10, 8, tzinfo=UTC).date(),
            generated_at=datetime(2026, 10, 9, tzinfo=UTC),
        )
    counts_after = {
        t: session.scalar(select(func.count()).select_from(Base.metadata.tables[t]))
        for t in ("video_snapshots", "monitoring_cycle_runs", "keyword_scan_runs")
    }
    assert counts_before == counts_after


def test_markdown_labels_generation_read_models() -> None:
    report = {
        "utc_day": "2026-10-08",
        "generated_at_utc": "2026-10-09T12:00:00+00:00",
        "window_start_utc": "2026-10-08T00:00:00+00:00",
        "window_end_utc": "2026-10-09T00:00:00+00:00",
        "day_complete": True,
        "discovery": {},
        "enrichment": {"utc_day_ledger": {"kinds": {}}, "attempt_table_outcomes_in_window": {"explanation": ""}},
        "monitoring": {},
        "outcome_capture": {"section_status": "unavailable"},
        "read_models": {
            "attention": {
                "latest_in_database_at_generation": {
                    "run_id": "a1",
                    "computed_at_utc": "2026-10-09T11:00:00+00:00",
                    "age_hours_relative_to_report_generation": 1.0,
                },
            },
            "keyword_performance": {},
        },
        "expansion_and_exploration": {"llm_expansion": {"status": "not_connected", "note": "x"}, "exploration": {}},
        "day_over_day": {"status": "skipped", "reason": "previous_utc_day_file_missing", "deltas": []},
    }
    md = render_radar_daily_observation_markdown(report)
    assert "latest at generation" in md
    assert "historical" not in md.lower()


def test_powershell_setup_dryrun() -> None:
    import subprocess

    ps1 = ROOT / "scripts" / "setup_daily_observation_scheduled_task.ps1"
    proc = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps1),
            "-Action",
            "DryRun",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "NicheScope-Radar-DailyObservationReport" in proc.stdout


def main() -> int:
    test_utc_day_window_boundaries()
    test_hit_at_window_end_excluded()
    test_original_immutable_and_revision()
    test_catch_up_missing_days()
    test_index_marks_missing_not_zero()
    test_monitoring_missing_ratio_null_when_selected_zero()
    test_monitoring_quiet_pool_diagnostic()
    test_monitoring_reconciliation_fields()
    test_read_models_split_day_end_vs_generation()
    test_day_over_day_skips_incomplete_current_day()
    test_day_over_day_missing_previous_file()
    test_optional_table_missing_not_zero()
    test_read_only_no_db_mutations()
    test_markdown_labels_generation_read_models()
    test_powershell_setup_dryrun()
    print("OK radar daily observation report tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
