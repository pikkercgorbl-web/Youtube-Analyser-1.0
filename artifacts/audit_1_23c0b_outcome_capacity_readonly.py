"""Stage 1.23C.0B read-only audit — optimized for large PG."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

UTC = timezone.utc


def _load_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("DATABASE_URL missing")


def main() -> None:
    url = _load_database_url()
    if "youtube_radar_restore_check" not in url:
        raise SystemExit("Refusing: expected youtube_radar_restore_check")
    engine = create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"})
    session = sessionmaker(bind=engine)()
    session.execute(text("SET TRANSACTION READ ONLY"))
    ref = session.scalar(text("SELECT (now() AT TIME ZONE 'utc')"))
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=UTC)
    print(f"database=youtube_radar_restore_check reference_utc={ref.isoformat()}")

    worker_first_cycle = session.scalar(text("SELECT min(started_at) FROM outcome_capture_cycle_runs"))
    worker_first_snap = session.scalar(
        text("SELECT min(captured_at) FROM video_snapshots WHERE source = 'keyword_outcome_worker'"),
    )
    worker_first = min(t for t in (worker_first_cycle, worker_first_snap) if t is not None)
    wd = worker_first.date()
    print(
        f"worker_epoch_utc: first_cycle={worker_first_cycle} first_snap={worker_first_snap} day={wd}",
    )

    core = text(
        """
        WITH earliest AS (
          SELECT DISTINCT ON (video_id)
            video_id, discovered_at, views_at_discovery, content_format, qualification_state, keyword_id
          FROM keyword_discovery_hits
          WHERE views_at_discovery IS NOT NULL
          ORDER BY video_id, discovered_at ASC, id ASC
        ),
        c AS (
          SELECT
            video_id,
            discovered_at,
            (discovered_at AT TIME ZONE 'UTC')::date AS cohort_day,
            discovered_at + interval '84 hours' AS window_end,
            content_format,
            qualification_state,
            keyword_id
          FROM earliest
        ),
        m AS (
          SELECT c.*,
            EXISTS (
              SELECT 1 FROM video_snapshots vs
              WHERE vs.video_id = c.video_id AND vs.views IS NOT NULL
                AND vs.captured_at >= c.discovered_at + interval '60 hours'
                AND vs.captured_at <= c.discovered_at + interval '84 hours'
            ) AS measured
          FROM c
          WHERE c.window_end <= (:ref)::timestamptz
        )
        SELECT
          count(*) AS matured_total,
          count(*) FILTER (WHERE measured) AS measured_total,
          count(*) FILTER (WHERE NOT measured) AS missing_total,
          count(*) FILTER (WHERE cohort_day < (:wd)::date) AS pre_worker_matured,
          count(*) FILTER (WHERE cohort_day < (:wd)::date AND measured) AS pre_worker_measured,
          count(*) FILTER (WHERE cohort_day >= (:wd)::date) AS post_worker_matured,
          count(*) FILTER (WHERE cohort_day >= (:wd)::date AND measured) AS post_worker_measured
        FROM m
        """,
    )
    print("\n=== Global matured coverage (earliest hit, window_end<=ref) ===")
    print(dict(session.execute(core, {"ref": ref, "wd": wd}).one()._mapping))

    daily = text(
        """
        WITH earliest AS (
          SELECT DISTINCT ON (video_id) video_id, discovered_at
          FROM keyword_discovery_hits
          WHERE views_at_discovery IS NOT NULL
          ORDER BY video_id, discovered_at ASC, id ASC
        ),
        c AS (
          SELECT
            video_id, discovered_at,
            (discovered_at AT TIME ZONE 'UTC')::date AS cohort_day,
            discovered_at + interval '84 hours' AS window_end
          FROM earliest
        )
        SELECT
          cohort_day,
          count(*) AS new_unique_videos,
          count(*) FILTER (WHERE window_end <= (:ref)::timestamptz) AS matured,
          count(*) FILTER (
            WHERE window_end <= (:ref)::timestamptz
              AND EXISTS (
                SELECT 1 FROM video_snapshots vs
                WHERE vs.video_id = c.video_id AND vs.views IS NOT NULL
                  AND vs.captured_at >= c.discovered_at + interval '60 hours'
                  AND vs.captured_at <= c.discovered_at + interval '84 hours'
              )
          ) AS measured,
          count(*) FILTER (WHERE window_end > (:ref)::timestamptz) AS immature
        FROM c
        GROUP BY cohort_day
        ORDER BY cohort_day DESC
        """,
    )
    print("\n=== Daily cohort rows (new / matured / measured / immature) — last 45 lines ===")
    all_days = session.execute(daily, {"ref": ref}).all()
    for row in all_days[:45]:
        d = row.cohort_day
        mat = row.matured or 0
        meas = row.measured or 0
        cov = round(100.0 * meas / mat, 2) if mat else None
        era = "pre" if d < wd else "post"
        print(f"{d} era={era} new={row.new_unique_videos} matured={mat} measured={meas} cov%={cov} immature={row.immature}")

    # Pre-worker rollup row
    pre = [r for r in all_days if r.cohort_day < wd]
    pre_mat = sum(r.matured or 0 for r in pre)
    pre_meas = sum(r.measured or 0 for r in pre)
    print(
        f"\npre_worker_cohort_days={len(pre)} matured_sum={pre_mat} measured_sum={pre_meas} "
        f"coverage%={round(100*pre_meas/pre_mat,2) if pre_mat else None}",
    )

    dup = text(
        """
        WITH earliest AS (
          SELECT DISTINCT ON (video_id) video_id, discovered_at
          FROM keyword_discovery_hits WHERE views_at_discovery IS NOT NULL
          ORDER BY video_id, discovered_at ASC, id ASC
        )
        SELECT
          (e.discovered_at AT TIME ZONE 'UTC')::date AS cohort_day,
          count(h.id) AS hit_rows,
          count(DISTINCT h.video_id) AS hit_videos
        FROM keyword_discovery_hits h
        JOIN earliest e ON e.video_id = h.video_id
        WHERE (h.discovered_at AT TIME ZONE 'UTC')::date = (e.discovered_at AT TIME ZONE 'UTC')::date
          AND h.views_at_discovery IS NOT NULL
          AND (e.discovered_at AT TIME ZONE 'UTC')::date >= (:wd)::date - interval '14 days'
        GROUP BY 1 ORDER BY 1 DESC LIMIT 14
        """,
    )
    print("\n=== Duplicate hits (same UTC day as earliest hit) recent ===")
    for row in session.execute(dup, {"wd": wd}).all():
        extra = row.hit_rows - row.hit_videos
        print(f"{row.cohort_day} hits={row.hit_rows} videos={row.hit_videos} extra_hits={extra}")

    kw_snaps = text(
        """
        SELECT (captured_at AT TIME ZONE 'UTC')::date AS d, count(*) AS n
        FROM video_snapshots WHERE source = 'keyword_outcome_worker'
          AND captured_at >= (:ref)::timestamptz - interval '21 days'
        GROUP BY 1 ORDER BY 1 DESC
        """,
    )
    print("\n=== keyword_outcome_worker snapshots by capture UTC day (21d) ===")
    for row in session.execute(kw_snaps, {"ref": ref}).all():
        print(dict(row._mapping))

    runs = text(
        """
        SELECT
          count(*) AS cycles,
          min(started_at) AS first_at, max(started_at) AS last_at,
          round(avg(runtime_seconds)::numeric,2) AS avg_runtime_s,
          round(avg(extract(epoch FROM (started_at - lag(started_at) OVER (ORDER BY started_at)))/3600.0)::numeric,2)
            FILTER (WHERE lag(started_at) OVER (ORDER BY started_at) IS NOT NULL) AS avg_gap_h,
          sum(selected_video_count) AS sel, sum(deferred_video_count) AS def,
          sum(inserted_snapshot_count) AS ins, sum(fetch_failed_count) AS fail,
          round(avg(unique_due_video_count)::numeric,1) AS avg_due,
          max(unique_due_video_count) AS max_due,
          sum(CASE WHEN deferred_video_count > 0 THEN 1 ELSE 0 END) AS cycles_with_defer
        FROM outcome_capture_cycle_runs
        """,
    )
    # avg gap needs subquery
    runs2 = text(
        """
        SELECT count(*) AS cycles, min(started_at) AS first_at, max(started_at) AS last_at,
          round(avg(runtime_seconds)::numeric,2) AS avg_runtime_s,
          sum(selected_video_count) AS sel, sum(deferred_video_count) AS def,
          sum(inserted_snapshot_count) AS ins, sum(fetch_failed_count) AS fail,
          sum(missing_video_count) AS miss_vid,
          round(avg(unique_due_video_count)::numeric,1) AS avg_unique_due,
          max(unique_due_video_count) AS max_unique_due,
          sum(CASE WHEN deferred_video_count > 0 THEN 1 ELSE 0 END) AS cycles_with_defer,
          sum(CASE WHEN cycle_status IN ('partial','failed') THEN 1 ELSE 0 END) AS bad_cycles
        FROM outcome_capture_cycle_runs
        """,
    )
    print("\n=== outcome_capture_cycle_runs ===")
    print(dict(session.execute(runs2).one()._mapping))

    gap = text(
        """
        WITH o AS (
          SELECT started_at, lag(started_at) OVER (ORDER BY started_at) prev FROM outcome_capture_cycle_runs
        )
        SELECT count(*) FILTER (WHERE started_at-prev > interval '3 hours') gaps_3h,
               count(*) FILTER (WHERE started_at-prev > interval '24 hours') gaps_24h,
               round(avg(extract(epoch FROM (started_at-prev))/3600.0)::numeric,2) avg_gap_h
        FROM o WHERE prev IS NOT NULL
        """,
    )
    print("cycle_gaps:", dict(session.execute(gap).one()._mapping))

    recent_cycles = text(
        """
        SELECT (started_at AT TIME ZONE 'UTC')::date d, count(*) cycles,
          sum(selected_video_count) sel, sum(inserted_snapshot_count) ins,
          sum(deferred_video_count) def, max(unique_due_video_count) max_due
        FROM outcome_capture_cycle_runs
        WHERE started_at >= (:ref)::timestamptz - interval '14 days'
        GROUP BY 1 ORDER BY 1 DESC
        """,
    )
    print("\n=== Worker cycles by UTC day (14d) ===")
    for row in session.execute(recent_cycles, {"ref": ref}).all():
        print(dict(row._mapping))

    inflow = text(
        """
        WITH earliest AS (
          SELECT DISTINCT ON (video_id) video_id, discovered_at
          FROM keyword_discovery_hits WHERE views_at_discovery IS NOT NULL
          ORDER BY video_id, discovered_at ASC, id ASC
        )
        SELECT (discovered_at AT TIME ZONE 'UTC')::date d, count(*) n FROM earliest
        WHERE discovered_at >= (:ref)::timestamptz - interval '21 days'
        GROUP BY 1 ORDER BY 1 DESC
        """,
    )
    print("\n=== New earliest-hit videos / UTC day ===")
    for row in session.execute(inflow, {"ref": ref}).all():
        print(dict(row._mapping))

    window_open = text(
        """
        WITH earliest AS (
          SELECT DISTINCT ON (video_id) video_id, discovered_at
          FROM keyword_discovery_hits WHERE views_at_discovery IS NOT NULL
          ORDER BY video_id, discovered_at ASC, id ASC
        )
        SELECT ((discovered_at + interval '60 hours') AT TIME ZONE 'UTC')::date d, count(*) n
        FROM earliest
        WHERE (discovered_at + interval '60 hours') >= (:ref)::timestamptz - interval '21 days'
        GROUP BY 1 ORDER BY 1 DESC
        """,
    )
    print("\n=== Outcome window opens (discovered+60h UTC day) ===")
    for row in session.execute(window_open, {"ref": ref}).all():
        print(dict(row._mapping))

    miss_attr = text(
        """
        WITH earliest AS (
          SELECT DISTINCT ON (video_id) video_id, discovered_at
          FROM keyword_discovery_hits WHERE views_at_discovery IS NOT NULL
          ORDER BY video_id, discovered_at ASC, id ASC
        ),
        m AS (
          SELECT e.video_id, e.discovered_at, (e.discovered_at AT TIME ZONE 'UTC')::date cohort_day
          FROM earliest e
          WHERE e.discovered_at + interval '84 hours' <= (:ref)::timestamptz
            AND NOT EXISTS (
              SELECT 1 FROM video_snapshots vs
              WHERE vs.video_id = e.video_id AND vs.views IS NOT NULL
                AND vs.captured_at BETWEEN e.discovered_at + interval '60 hours'
                                     AND e.discovered_at + interval '84 hours'
            )
        )
        SELECT
          count(*) total_missing,
          count(*) FILTER (WHERE cohort_day < (:wd)::date) legacy_pre_worker,
          count(*) FILTER (WHERE cohort_day >= (:wd)::date) post_worker_cohort,
          count(*) FILTER (
            WHERE EXISTS (SELECT 1 FROM video_snapshots s WHERE s.video_id=m.video_id AND s.source='keyword_outcome_worker')
          ) any_kw_worker_snap,
          count(*) FILTER (
            WHERE EXISTS (
              SELECT 1 FROM video_snapshots s WHERE s.video_id=m.video_id AND s.source='keyword_outcome_worker'
                AND s.captured_at BETWEEN m.discovered_at + interval '60 hours'
                                    AND m.discovered_at + interval '84 hours'
            )
          ) kw_worker_in_window
        FROM m
        """,
    )
    print("\n=== Missingness buckets (matured, no valid outcome) ===")
    print(dict(session.execute(miss_attr, {"ref": ref, "wd": wd}).one()._mapping))

    fmt = text(
        """
        WITH earliest AS (
          SELECT DISTINCT ON (video_id) video_id, discovered_at, content_format
          FROM keyword_discovery_hits WHERE views_at_discovery IS NOT NULL
          ORDER BY video_id, discovered_at ASC, id ASC
        ),
        matured AS (
          SELECT * FROM earliest WHERE discovered_at + interval '84 hours' <= (:ref)::timestamptz
        )
        SELECT content_format, count(*) matured,
          count(*) FILTER (WHERE EXISTS (
            SELECT 1 FROM video_snapshots vs WHERE vs.video_id=matured.video_id AND vs.views IS NOT NULL
              AND vs.captured_at BETWEEN matured.discovered_at + interval '60 hours'
                                   AND matured.discovered_at + interval '84 hours'
          )) measured
        FROM matured GROUP BY 1 ORDER BY matured DESC
        """,
    )
    print("\n=== content_format bias (matured) ===")
    for row in session.execute(fmt, {"ref": ref}).all():
        pct = round(100.0 * row.measured / row.matured, 2) if row.matured else None
        print(f"{row.content_format} matured={row.matured} measured={row.measured} pct={pct}")

    # Latest cycle snapshot
    last = session.execute(
        text(
            """
            SELECT started_at, unique_due_video_count, selected_video_count, deferred_video_count,
              inserted_snapshot_count, fetch_failed_count, expired_count, capture_due_count, capture_overdue_count
            FROM outcome_capture_cycle_runs ORDER BY started_at DESC LIMIT 1
            """,
        ),
    ).one()
    print("\n=== Latest cycle run ===")
    print(dict(last._mapping))

    # Post-worker mature cohort days only - last 14 with matured>0
    post_days = [
        r for r in all_days if r.cohort_day >= wd and (r.matured or 0) > 0
    ][:14]
    print("\n=== Post-worker MATURE cohort UTC days (up to 14) ===")
    for row in post_days:
        mat, meas = row.matured, row.measured
        print(f"{row.cohort_day} matured={mat} measured={meas} cov%={round(100*meas/mat,2) if mat else None}")

    session.close()
    print("\nDONE")


if __name__ == "__main__":
    main()
