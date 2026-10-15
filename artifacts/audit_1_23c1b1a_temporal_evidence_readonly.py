"""Stage 1.23C.1B.1A temporal evidence audit (read-only PG)."""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.orm import DailyIntelligenceReport, DailyIntelligenceReportWinnerFinding, VideoSnapshot
from app.services.daily_intelligence_outcome_followup import get_winner_outcome_followup
from app.services.keyword_performance_evaluation import HORIZON_HOURS, HORIZON_SNAPSHOT_TOLERANCE_HOURS
from app.services.metrics import ensure_utc, utc_now
from app.services.video_snapshot_storage import get_latest_snapshots_for_videos

UTC = timezone.utc


def _load_database_url() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    env_path = ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def main() -> None:
    url = _load_database_url()
    if not url or "youtube_radar_restore_check" not in url:
        print("Refusing: DATABASE_URL must target youtube_radar_restore_check")
        sys.exit(1)

    engine = create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"})
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    session.execute(text("SET TRANSACTION READ ONLY"))
    ref = utc_now()
    print(f"database={session.scalar(text('SELECT current_database()'))} reference_now={ref.isoformat()}")

    findings = list(session.scalars(select(DailyIntelligenceReportWinnerFinding)).all())
    print(f"finding_rows={len(findings)}")

    post_signal = 0
    post_comparable_baseline = 0
    post_baseline_snap_after_outcome = 0
    post_baseline_snap_after_edition = 0
    post_views_fallback_no_snap = 0
    growth_ratio_computed = 0
    growth_suspicious = 0

    for f in findings:
        report = session.get(DailyIntelligenceReport, f.report_date)
        if report is None or report.source_computed_at is None:
            continue
        row = get_winner_outcome_followup(session, f.report_date, f.video_id, reference_now=ref)
        if row is None:
            continue
        if row["coverage_category"] != "MEASURED_POST_SIGNAL":
            continue
        post_signal += 1
        payload = json.loads(f.payload_json or "{}")
        prov = json.loads(f.discovery_provenance_json or "{}")
        edition = ensure_utc(report.source_computed_at)
        frozen_views = payload.get("views")
        metrics = row.get("comparison_metrics") or {}
        if metrics.get("growth_ratio") is not None:
            growth_ratio_computed += 1

        latest_unbounded = get_latest_snapshots_for_videos(session, [f.video_id]).get(f.video_id)
        latest_at_edition = get_latest_snapshots_for_videos(
            session,
            [f.video_id],
            compute_before=edition,
        ).get(f.video_id)

        outcome_cap = row.get("outcome_measurement", {}).get("snapshot_captured_at")
        outcome_dt = datetime.fromisoformat(outcome_cap.replace("Z", "+00:00")) if outcome_cap else None

        if frozen_views is not None and metrics.get("views_at_attention") is not None:
            post_comparable_baseline += 1

        if latest_unbounded and outcome_dt:
            if ensure_utc(latest_unbounded.captured_at) > ensure_utc(outcome_dt):
                post_baseline_snap_after_outcome += 1
        if latest_at_edition and outcome_dt:
            if ensure_utc(latest_at_edition.captured_at) > ensure_utc(outcome_dt):
                post_baseline_snap_after_outcome += 0  # counted above

        if latest_at_edition is None and frozen_views is not None:
            post_views_fallback_no_snap += 1
        elif latest_at_edition and frozen_views is not None:
            if int(latest_at_edition.views or -1) != int(frozen_views):
                growth_suspicious += 1
            if ensure_utc(latest_at_edition.captured_at) > edition + timedelta(minutes=5):
                post_baseline_snap_after_edition += 1

    cats = Counter()
    for f in findings:
        row = get_winner_outcome_followup(session, f.report_date, f.video_id, reference_now=ref)
        if row:
            cats[row["coverage_category"]] += 1

    print("\n=== Coverage distribution (live recompute) ===")
    print(dict(cats))
    print("\n=== Post-signal temporal checks ===")
    print(f"MEASURED_POST_SIGNAL={post_signal}")
    print(f"post_with_frozen_views_baseline={post_comparable_baseline}")
    print(f"post_growth_ratio_computed={growth_ratio_computed}")
    print(f"post_latest_snap_in_db_after_outcome={post_baseline_snap_after_outcome}")
    print(f"post_frozen_views_ne_latest_at_edition={growth_suspicious}")
    print(f"post_no_snap_at_or_before_edition={post_views_fallback_no_snap}")
    print(f"post_latest_at_edition_captured_after_edition_5m={post_baseline_snap_after_edition}")


if __name__ == "__main__":
    main()
