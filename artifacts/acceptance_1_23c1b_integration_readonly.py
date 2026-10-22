"""Stage 1.23C.1B final integration acceptance — READ ONLY on youtube_radar_restore_check."""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import get_db
from app.models.orm import DailyIntelligenceReport, DailyIntelligenceReportWinnerFinding
from app.models.schemas import (
    DailyIntelligenceOutcomeCoverageResponse,
    DailyIntelligenceWinnerOutcomeFollowUpResponse,
)
from app.main import app
from app.services.daily_intelligence_outcome_followup import (
    get_report_outcome_coverage,
    get_winner_outcome_followup,
)
from fastapi.testclient import TestClient

EXPECTED_DB = "youtube_radar_restore_check"
ARTIFACT_PATH = ROOT / "artifacts" / "acceptance_1_23c1b_integration_report.json"


def _load_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        env_path = ROOT / ".env"
        if env_path.is_file():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("DATABASE_URL="):
                    url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not url:
        raise SystemExit("DATABASE_URL missing")
    if EXPECTED_DB not in url:
        raise SystemExit(f"Refusing: expected database name {EXPECTED_DB!r} in URL")
    return url


def _readonly_session_factory(url: str):
    engine = create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"})
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _pick_report_date(session) -> date | None:
    row = session.execute(
        text(
            """
            SELECT f.report_date, COUNT(*) AS n
            FROM daily_intelligence_report_winner_findings f
            JOIN daily_intelligence_reports r ON r.report_date = f.report_date
            GROUP BY f.report_date
            ORDER BY n DESC
            LIMIT 1
            """
        )
    ).first()
    if not row:
        return None
    return row[0]


def _nullable_zero_violations(payload: dict) -> list[str]:
    issues: list[str] = []
    cm = payload.get("comparison_metrics") or {}
    for key in (
        "views_at_attention_frozen",
        "views_at_outcome_horizon",
        "delta_views_descriptive",
        "descriptive_growth_ratio",
        "verified_post_signal_growth",
        "verified_post_signal_growth_ratio",
    ):
        if key not in cm:
            continue
        val = cm[key]
        if val is None:
            continue
        prov = payload.get("attention_views_provenance") or {}
        if key == "views_at_attention_frozen" and prov.get("frozen_attention_views") is None and val == 0:
            issues.append(f"{key} is 0 while frozen_attention_views is null")
    om = payload.get("outcome_measurement") or {}
    if om.get("snapshot_captured_at") is None and om.get("views_at_outcome_horizon") == 0:
        issues.append("views_at_outcome_horizon is 0 without snapshot")
    return issues


def main() -> None:
    url = _load_database_url()
    SessionLocal = _readonly_session_factory(url)
    session = SessionLocal()
    session.execute(text("SET TRANSACTION READ ONLY"))
    db_name = session.scalar(text("SELECT current_database()"))
    ro = session.scalar(text("SHOW transaction_read_only"))

    report: dict = {
        "database": db_name,
        "transaction_read_only": ro,
        "checks": [],
        "coverage_by_date": {},
        "examples": {},
        "api_http": {},
        "performance": {},
        "verdict_inputs": {},
    }

    def add_check(name: str, ok: bool, detail: str | dict):
        report["checks"].append({"name": name, "ok": ok, "detail": detail})

    report_date = _pick_report_date(session)
    if report_date is None:
        add_check("has_findings", False, "no winner findings in DB")
        ARTIFACT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        raise SystemExit(2)

    rd_iso = report_date.isoformat()
    add_check("has_findings", True, rd_iso)

    t0 = time.perf_counter()
    raw_coverage = get_report_outcome_coverage(session, report_date)
    coverage_ms = (time.perf_counter() - t0) * 1000
    report["performance"]["coverage_service_ms"] = round(coverage_ms, 2)

    if raw_coverage is None:
        add_check("coverage_service", False, "None")
    else:
        cov_model = DailyIntelligenceOutcomeCoverageResponse.model_validate(raw_coverage)
        add_check("coverage_pydantic", True, "ok")
        winner_count = cov_model.winner_count
        counts = cov_model.coverage_by_category or cov_model.coverage_counts or {}
        sum_counts = sum(counts.values())
        add_check(
            "coverage_sum_equals_winner_count",
            sum_counts == winner_count,
            {"winner_count": winner_count, "sum_counts": sum_counts, "counts": counts},
        )
        item_ids = [i.video_id for i in cov_model.items]
        add_check(
            "coverage_one_entry_per_finding",
            len(item_ids) == winner_count and len(set(item_ids)) == len(item_ids),
            {"items_len": len(item_ids), "unique": len(set(item_ids))},
        )
        report["coverage_by_date"][rd_iso] = {
            "winner_count": winner_count,
            "coverage_by_category": dict(counts),
            "edition_signal": cov_model.edition_signal_source_computed_at,
            "reference_evaluated_at": cov_model.reference_evaluated_at,
        }

        by_cat: dict[str, str] = {}
        for item in cov_model.items:
            cat = item.coverage_category
            if cat not in by_cat:
                by_cat[cat] = item.video_id
        report["verdict_inputs"]["categories_on_primary_date"] = sorted(by_cat.keys())

        for cat, vid in sorted(by_cat.items()):
            t1 = time.perf_counter()
            follow_raw = get_winner_outcome_followup(session, report_date, vid)
            follow_ms = (time.perf_counter() - t1) * 1000
            if follow_raw is None:
                report["examples"][cat] = {"video_id": vid, "error": "follow-up None"}
                continue
            follow_model = DailyIntelligenceWinnerOutcomeFollowUpResponse.model_validate(follow_raw)
            anchor = follow_model.discovery_outcome_anchor or {}
            example = {
                "video_id": vid,
                "rank": follow_model.rank,
                "coverage_category": follow_model.coverage_category,
                "outcome_window_phase": follow_model.outcome_window_phase,
                "edition_signal": (follow_model.signal_timestamps or {}).get(
                    "edition_signal_source_computed_at"
                ),
                "discovered_at": anchor.get("discovered_at"),
                "outcome_window_target_at": anchor.get("outcome_window_target_at"),
                "horizon_hours": anchor.get("horizon_hours"),
                "tolerance_hours": anchor.get("tolerance_hours"),
                "outcome_snapshot_at": (follow_model.outcome_measurement or {}).get("snapshot_captured_at"),
                "attention_views_source": follow_model.attention_views_provenance.attention_views_source,
                "baseline_provenance_verified": follow_model.attention_views_provenance.baseline_provenance_verified,
                "metrics_interpretation": follow_model.metrics_interpretation,
                "comparison_metrics": dict(follow_model.comparison_metrics or {}),
                "frozen_delayed_outcome": dict(follow_model.frozen_delayed_outcome or {}),
                "reference_evaluated_at": follow_model.reference_evaluated_at,
                "followup_service_ms": round(follow_ms, 2),
                "nullable_zero_issues": _nullable_zero_violations(follow_raw),
            }
            report["examples"][cat] = example

        missing_cats = [
            c
            for c in (
                "MEASURED_POST_SIGNAL",
                "MEASURED_PRE_SIGNAL",
                "NOT_MATURED",
                "MATURED_MISSING",
                "INVALID_TIMELINE",
                "INSUFFICIENT_EVIDENCE",
            )
            if c not in by_cat
        ]
        report["verdict_inputs"]["missing_categories_on_primary_date"] = missing_cats

    # HTTP via TestClient + read-only dependency
    def _override_get_db():
        s = SessionLocal()
        s.execute(text("SET TRANSACTION READ ONLY"))
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app)
    try:
        r_cov = client.get(f"/api/daily-intelligence/reports/{rd_iso}/outcome-coverage")
        report["api_http"]["outcome_coverage"] = {
            "status": r_cov.status_code,
            "ok": r_cov.status_code == 200,
        }
        add_check("http_outcome_coverage", r_cov.status_code == 200, r_cov.status_code)
        if r_cov.status_code == 200:
            DailyIntelligenceOutcomeCoverageResponse.model_validate(r_cov.json())

        sample_vid = None
        if raw_coverage and raw_coverage.get("items"):
            sample_vid = raw_coverage["items"][0]["video_id"]
        if sample_vid:
            r_fu = client.get(
                f"/api/daily-intelligence/reports/{rd_iso}/winners/{sample_vid}/outcome-follow-up",
            )
            report["api_http"]["outcome_follow_up"] = {
                "status": r_fu.status_code,
                "video_id": sample_vid,
                "ok": r_fu.status_code == 200,
            }
            add_check("http_outcome_follow_up", r_fu.status_code == 200, r_fu.status_code)
            if r_fu.status_code == 200:
                DailyIntelligenceWinnerOutcomeFollowUpResponse.model_validate(r_fu.json())
    finally:
        app.dependency_overrides.clear()

    # Global category counts across all report dates (read-only aggregate)
    rows = session.execute(
        text(
            """
            SELECT report_date::text, COUNT(*) AS winners
            FROM daily_intelligence_report_winner_findings
            GROUP BY report_date
            ORDER BY winners DESC
            LIMIT 5
            """
        )
    ).fetchall()
    report["verdict_inputs"]["top_report_dates_by_winners"] = [
        {"report_date": r[0], "winners": r[1]} for r in rows
    ]

    failed = [c for c in report["checks"] if not c["ok"]]
    report["summary"] = {
        "primary_report_date": rd_iso,
        "checks_passed": len(report["checks"]) - len(failed),
        "checks_failed": len(failed),
        "failed_names": [c["name"] for c in failed],
    }

    ARTIFACT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    session.close()
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
