"""Stage 1.23C.0 read-only PG audit (do not run writes). Ephemeral artifact."""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

import app.models.orm  # noqa: F401
from app.models.orm import (
    DailyIntelligenceReportWinnerFinding,
    DailyIntelligenceRunWinnerAppearance,
    KeywordDiscoveryHit,
    VideoSnapshot,
)
from app.services.attention_delayed_outcome import delayed_outcome_for_video
from app.services.delayed_outcome_capture_config import OUTCOME_CAPTURE_SOURCE
from app.services.keyword_performance_evaluation import (
    HORIZON_HOURS,
    HORIZON_SNAPSHOT_TOLERANCE_HOURS,
    KeywordVideoBaseline,
    match_horizon_outcome,
)
from app.services.metrics import ensure_utc, utc_now
from app.services.snapshot_collection_policy import MONITORING_CAPTURE_SOURCE
from app.services.video_snapshot_storage import get_snapshots_for_videos

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
    if not url:
        print("DATABASE_URL missing")
        sys.exit(1)
    if "youtube_radar_restore_check" not in url:
        print("Refusing: expected youtube_radar_restore_check")
        sys.exit(1)
    engine = create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"})
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    session.execute(text("SET TRANSACTION READ ONLY"))
    db_name = session.scalar(text("SELECT current_database()"))
    ro = session.scalar(text("SHOW transaction_read_only"))
    now = utc_now()
    print(f"database={db_name} read_only={ro} reference_now={now.isoformat()}")

    findings = list(session.scalars(select(DailyIntelligenceReportWinnerFinding)).all())
    appearances = list(session.scalars(select(DailyIntelligenceRunWinnerAppearance)).all())
    unique_finding_videos = {f.video_id for f in findings}
    unique_appearance_videos = {a.video_id for a in appearances}

    print("\n=== A/B inventory ===")
    print(f"report_winner_findings_rows={len(findings)} unique_video_id={len(unique_finding_videos)}")
    print(f"run_winner_appearances_rows={len(appearances)} unique_video_id={len(unique_appearance_videos)}")
    report_dates = Counter(str(f.report_date) for f in findings)
    print(f"findings_by_report_date={dict(sorted(report_dates.items()))}")

    # C — discovery provenance on frozen rows
    prov_available = 0
    prov_missing = 0
    prov_no_views = 0
    prov_invalid_ts = 0
    for f in findings:
        try:
            prov = json.loads(f.discovery_provenance_json or "{}")
        except json.JSONDecodeError:
            prov_invalid_ts += 1
            continue
        if prov.get("available") is True:
            da = prov.get("discovered_at")
            if not da:
                prov_invalid_ts += 1
            else:
                prov_available += 1
        elif prov.get("reason") == "no_views_at_discovery":
            prov_no_views += 1
        elif prov.get("reason") == "no_discovery_hits":
            prov_missing += 1
        else:
            prov_missing += 1

    print("\n=== C discovery_provenance_json (frozen at DI lock) ===")
    print(
        f"available={prov_available} no_discovery_hits={prov_missing} "
        f"no_views_at_discovery={prov_no_views} invalid_json_or_ts={prov_invalid_ts}",
    )

    all_video_ids = sorted(unique_finding_videos | unique_appearance_videos)
    snapshots_by_video: dict[str, list] = defaultdict(list)
    for snap in get_snapshots_for_videos(session, all_video_ids):
        snapshots_by_video[snap.video_id].append(snap)
    hits_by_video: dict[str, list] = defaultdict(list)
    for hit in session.scalars(select(KeywordDiscoveryHit).where(KeywordDiscoveryHit.video_id.in_(all_video_ids))).all():
        hits_by_video[hit.video_id].append(hit)

    # Per finding row (report_date + video) — canonical historical unit
    attention_states = Counter()
    worker_states = Counter()
    coverage_cat = Counter()
    frozen_vs_now = Counter()
    pre_post_signal = Counter()
    snapshot_sources_at_outcome = Counter()
    latency_attention_to_outcome: list[float] = []

    tol = timedelta(hours=HORIZON_SNAPSHOT_TOLERANCE_HOURS)
    horizon = timedelta(hours=HORIZON_HOURS)

    def worker_state(discovered_at: datetime, satisfied: bool) -> str:
        target = ensure_utc(discovered_at) + horizon
        ws, we = target - tol, target + tol
        ref = ensure_utc(now)
        if satisfied:
            return "satisfied"
        if ref > we:
            return "expired"
        if ref < ws:
            return "pending"
        if ref <= target:
            return "capture_due"
        return "capture_overdue"

    for f in findings:
        prov = json.loads(f.discovery_provenance_json or "{}")
        payload = json.loads(f.payload_json or "{}")
        frozen_delayed = payload.get("delayed_outcome_state")
        frozen_growth = payload.get("delayed_outcome_growth")
        source_computed_at = None
        # latest appearance on same report_date for signal time
        app_rows = [a for a in appearances if a.video_id == f.video_id and a.report_date == f.report_date]
        if app_rows:
            source_computed_at = max(ensure_utc(a.source_computed_at) for a in app_rows)
        else:
            source_computed_at = None

        snaps = snapshots_by_video.get(f.video_id, [])
        hits = hits_by_video.get(f.video_id, [])
        att_state, att_growth = delayed_outcome_for_video(
            video_id=f.video_id,
            hits=hits,
            snapshots=snaps,
            now=now,
        )
        attention_states[att_state] += 1

        if prov.get("available") is not True:
            coverage_cat["INSUFFICIENT_EVIDENCE"] += 1
            worker_states["unavailable_provenance"] += 1
            continue

        discovered_at = datetime.fromisoformat(prov["discovered_at"].replace("Z", "+00:00"))
        if discovered_at.tzinfo is None:
            discovered_at = discovered_at.replace(tzinfo=UTC)
        baseline = KeywordVideoBaseline(
            keyword_id=int(prov.get("keyword_id") or 0),
            video_id=f.video_id,
            discovery_at=discovered_at,
            views_at_discovery=prov.get("views_at_discovery"),
            vph_at_discovery=prov.get("vph_at_discovery"),
        )
        outcome = match_horizon_outcome(baseline, snapshots_by_video, tolerance_hours=HORIZON_SNAPSHOT_TOLERANCE_HOURS)
        satisfied = outcome is not None
        ws = worker_state(discovered_at, satisfied)
        worker_states[ws] += 1

        target = ensure_utc(discovered_at) + horizon
        if ensure_utc(now) < target:
            coverage_cat["NOT_MATURED"] += 1
        elif outcome is None:
            coverage_cat["MATURED_MISSING"] += 1
        elif source_computed_at is None:
            coverage_cat["MEASURED_NO_ATTENTION_TS"] += 1
        elif outcome.snapshot_captured_at < source_computed_at:
            coverage_cat["MEASURED_PRE_SIGNAL"] += 1
            pre_post_signal["pre"] += 1
        else:
            coverage_cat["MEASURED_POST_SIGNAL"] += 1
            pre_post_signal["post"] += 1
            latency_attention_to_outcome.append(
                (outcome.snapshot_captured_at - source_computed_at).total_seconds() / 3600.0,
            )

        if frozen_delayed != att_state:
            frozen_vs_now[f"{frozen_delayed}_now_{att_state}"] += 1
        else:
            frozen_vs_now["unchanged"] += 1

        if outcome is not None:
            # best snapshot in window — source breakdown
            best_snap = None
            best_delta = None
            for snap in snaps:
                if snap.views is None:
                    continue
                cap = ensure_utc(snap.captured_at)
                delta = abs(cap - target)
                if delta <= tol and (best_delta is None or delta < best_delta):
                    best_delta = delta
                    best_snap = snap
            if best_snap:
                snapshot_sources_at_outcome[best_snap.source] += 1

    print("\n=== D Attention delayed_outcome_for_video (current DB snapshots, earliest hit) ===")
    print(dict(attention_states))
    print("\n=== D Worker planner states (same baseline) ===")
    print(dict(worker_states))
    print("\n=== Step 2 coverage categories (per finding row) ===")
    print(dict(coverage_cat))
    print("\n=== D1 frozen delayed_outcome_state vs recomputed now ===")
    print(dict(frozen_vs_now))
    print("\n=== Outcome snapshot source (in ±12h window) ===")
    print(dict(snapshot_sources_at_outcome))

    if latency_attention_to_outcome:
        lat = sorted(latency_attention_to_outcome)
        print(
            f"\n=== E latency hours outcome_captured_at - source_computed_at (post-signal only) n={len(lat)} "
            f"min={lat[0]:.2f} p50={lat[len(lat)//2]:.2f} max={lat[-1]:.2f}",
        )

    # G — views at attention vs outcome for post-signal subset
    views_at_attn = 0
    views_at_out = 0
    both = 0
    for f in findings:
        prov = json.loads(f.discovery_provenance_json or "{}")
        if prov.get("available") is not True:
            continue
        payload = json.loads(f.payload_json or "{}")
        app_rows = [a for a in appearances if a.video_id == f.video_id and a.report_date == f.report_date]
        if not app_rows:
            continue
        source_computed_at = max(ensure_utc(a.source_computed_at) for a in app_rows)
        discovered_at = datetime.fromisoformat(prov["discovered_at"].replace("Z", "+00:00"))
        if discovered_at.tzinfo is None:
            discovered_at = discovered_at.replace(tzinfo=UTC)
        baseline = KeywordVideoBaseline(
            keyword_id=int(prov.get("keyword_id") or 0),
            video_id=f.video_id,
            discovery_at=discovered_at,
            views_at_discovery=prov.get("views_at_discovery"),
            vph_at_discovery=prov.get("vph_at_discovery"),
        )
        outcome = match_horizon_outcome(baseline, snapshots_by_video, tolerance_hours=HORIZON_SNAPSHOT_TOLERANCE_HOURS)
        if outcome is None or outcome.snapshot_captured_at < source_computed_at:
            continue
        attn_views = payload.get("views")
        if attn_views is not None:
            views_at_attn += 1
        if outcome.outcome_views is not None:
            views_at_out += 1
        if attn_views is not None and outcome.outcome_views is not None:
            both += 1

    print(f"\n=== G post-signal comparable: payload.views present={views_at_attn} outcome_views={views_at_out} both={both}")

    # H repeats
    by_vid_runs = Counter(a.video_id for a in appearances)
    by_vid_days: dict[str, set] = defaultdict(set)
    for a in appearances:
        by_vid_days[a.video_id].add(a.report_date)
    multi_run = sum(1 for v, c in by_vid_runs.items() if c > 1)
    multi_day = sum(1 for v, days in by_vid_days.items() if len(days) > 1)

    print("\n=== H repeat appearances ===")
    print(f"unique_videos_in_appearances={len(by_vid_runs)} total_appearance_rows={len(appearances)}")
    print(f"videos_in_multiple_runs={multi_run} videos_in_multiple_report_dates={multi_day}")

    # Snapshot inventory for DI videos
    src_counts = Counter()
    for vid in all_video_ids:
        for s in snapshots_by_video.get(vid, []):
            src_counts[s.source] += 1
    print("\n=== Snapshot rows for DI-related video_ids by source ===")
    print(dict(src_counts.most_common(10)))

    # Monitoring 72h checkpoint vs outcome worker for sample stats
    mon_72 = 0
    out_72 = 0
    for vid in all_video_ids:
        for s in snapshots_by_video.get(vid, []):
            if s.age_hours is not None and abs(float(s.age_hours) - 72.0) <= 12:
                if s.source == MONITORING_CAPTURE_SOURCE:
                    mon_72 += 1
                if s.source == OUTCOME_CAPTURE_SOURCE:
                    out_72 += 1

    print(f"approx_age_72h_snapshots monitoring_worker={mon_72} keyword_outcome_worker={out_72}")

    frozen_delayed = Counter(json.loads(f.payload_json or "{}").get("delayed_outcome_state") for f in findings)
    print("\n=== Frozen payload delayed_outcome_state (DI findings) ===")
    print(dict(frozen_delayed))

    # Global corpus: distinct videos with discovery hits
    global_videos = session.scalar(
        select(func.count(func.distinct(KeywordDiscoveryHit.video_id))),
    )
    outcome_worker_total = session.scalar(
        select(func.count()).select_from(VideoSnapshot).where(VideoSnapshot.source == OUTCOME_CAPTURE_SOURCE),
    )
    monitoring_total = session.scalar(
        select(func.count()).select_from(VideoSnapshot).where(VideoSnapshot.source == MONITORING_CAPTURE_SOURCE),
    )
    print("\n=== Global DB (context) ===")
    print(f"distinct_videos_with_discovery_hits={global_videos}")
    print(f"video_snapshots monitoring_worker={monitoring_total} keyword_outcome_worker={outcome_worker_total}")

    # Sample matured videos globally (earliest hit per video, views_at_discovery set)
    sample_matured = 0
    sample_valid = 0
    sample_missing = 0
    sample_pending = 0
    hits_all = list(session.scalars(select(KeywordDiscoveryHit).order_by(KeywordDiscoveryHit.discovered_at.asc())).all())
    earliest: dict[str, KeywordDiscoveryHit] = {}
    for h in hits_all:
        if h.video_id not in earliest and h.views_at_discovery is not None:
            earliest[h.video_id] = h
    snap_global = defaultdict(list)
    for snap in get_snapshots_for_videos(session, list(earliest.keys())[:500]):
        snap_global[snap.video_id].append(snap)
    for vid, hit in list(earliest.items())[:500]:
        st, _ = delayed_outcome_for_video(
            video_id=vid,
            hits=[hit],
            snapshots=snap_global.get(vid, []),
            now=now,
        )
        if st == "pending":
            sample_pending += 1
        elif st == "missing":
            sample_missing += 1
        elif st in ("confirmed", "not_confirmed"):
            sample_valid += 1
            sample_matured += 1
        elif st == "unavailable":
            pass
    print(
        f"global_earliest_hit_sample_n={min(500, len(earliest))} "
        f"pending={sample_pending} valid_outcome={sample_valid} missing={sample_missing}",
    )

    # Duplicate snapshot integrity for DI videos
    dup_check = session.execute(
        text(
            """
            SELECT video_id, captured_at, source, COUNT(*) AS c
            FROM video_snapshots
            WHERE video_id = ANY(:ids)
            GROUP BY video_id, captured_at, source
            HAVING COUNT(*) > 1
            LIMIT 5
            """,
        ),
        {"ids": all_video_ids},
    ).all()
    print(f"duplicate_snapshot_groups_among_di_videos={len(dup_check)}")

    row = session.execute(
        text(
            """
            WITH earliest AS (
              SELECT DISTINCT ON (video_id) video_id, discovered_at, views_at_discovery
              FROM keyword_discovery_hits
              WHERE views_at_discovery IS NOT NULL
              ORDER BY video_id, discovered_at ASC, id ASC
            ),
            matured AS (
              SELECT *, discovered_at + interval '84 hours' AS window_end
              FROM earliest
              WHERE discovered_at + interval '72 hours' <= (now() AT TIME ZONE 'utc')
            )
            SELECT
              (SELECT count(*) FROM earliest) AS videos_with_usable_discovery,
              (SELECT count(*) FROM matured) AS matured_videos,
              (SELECT count(*) FROM matured m WHERE NOT EXISTS (
                SELECT 1 FROM video_snapshots vs
                WHERE vs.video_id = m.video_id AND vs.views IS NOT NULL
                  AND vs.captured_at >= m.discovered_at + interval '60 hours'
                  AND vs.captured_at <= m.discovered_at + interval '84 hours'
              )) AS matured_missing_inwindow,
              (SELECT count(*) FROM matured m WHERE EXISTS (
                SELECT 1 FROM video_snapshots vs
                WHERE vs.video_id = m.video_id AND vs.views IS NOT NULL
                  AND vs.captured_at >= m.discovered_at + interval '60 hours'
                  AND vs.captured_at <= m.discovered_at + interval '84 hours'
              )) AS matured_with_inwindow
            """,
        ),
    ).one()
    print("\n=== Global earliest-hit maturity (SQL ±12h window) ===")
    print(dict(row._mapping))

    session.close()
    print("\nDONE read-only audit")


if __name__ == "__main__":
    main()
