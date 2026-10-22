"""Stage 1.23C.0C — priority outcome capture feasibility (read-only + offline sim)."""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

UTC = timezone.utc
BUDGET = 100
TOL_H = 12
HORIZON_H = 72


def _url() -> str:
    u = os.environ.get("DATABASE_URL")
    if u:
        return u
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("no DATABASE_URL")


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def window_bounds(discovered_at: datetime) -> tuple[datetime, datetime]:
    d = _utc(discovered_at)
    return d + timedelta(hours=HORIZON_H - TOL_H), d + timedelta(hours=HORIZON_H + TOL_H)


@dataclass
class VideoState:
    video_id: str
    discovered_at: datetime
    window_start: datetime
    window_end: datetime
    first_attention: datetime | None = None
    is_edition_winner: bool = False
    is_appearance: bool = False
    report_date: object | None = None
    has_outcome: bool = False
    captured_at: datetime | None = None
    eligible_at_attention: bool = False
    window_closed_at_attention: bool = False


@dataclass
class SimResult:
    name: str
    priority_captured: int = 0
    priority_missed: int = 0
    bg_captured: int = 0
    bg_missed: int = 0
    cycles: int = 0
    slots_used: int = 0
    priority_slots: int = 0
    bg_slots: int = 0
    notes: list[str] = field(default_factory=list)


def simulate(
    *,
    name: str,
    cycle_times: list[datetime],
    videos: dict[str, VideoState],
    priority_ids: set[str],
    reserve: int | None,
    dynamic: bool,
) -> SimResult:
    """Counterfactual: selecting a video => successful in-window capture at cycle time."""
    res = SimResult(name=name)
    satisfied: set[str] = {v.video_id for v in videos.values() if v.has_outcome}
    res.cycles = len(cycle_times)

    for t in cycle_times:
        t = _utc(t)
        due: list[tuple[float, str, bool]] = []
        for vid, st in videos.items():
            if vid in satisfied:
                continue
            if t < st.window_start or t > st.window_end:
                continue
            hours_left = (st.window_end - t).total_seconds() / 3600.0
            due.append((hours_left, vid, vid in priority_ids))
        due.sort(key=lambda x: (x[0], x[1]))

        pri_due = [x for x in due if x[2]]
        bg_due = [x for x in due if not x[2]]

        if dynamic:
            pri_cap = min(len(pri_due), reserve or 0)
            bg_cap = BUDGET - pri_cap
        elif reserve is not None and reserve > 0:
            pri_cap = min(len(pri_due), reserve)
            bg_cap = BUDGET - pri_cap
        else:
            pri_cap = 0
            bg_cap = BUDGET

        selected: list[str] = []
        for _, vid, _ in pri_due[:pri_cap]:
            selected.append(vid)
        for _, vid, _ in bg_due[: max(0, bg_cap)]:
            selected.append(vid)
        if not reserve and not dynamic:
            # policy A: global sort
            selected = [vid for _, vid, _ in due[:BUDGET]]

        res.slots_used += len(selected)
        for vid in selected:
            st = videos[vid]
            if st.window_start <= t <= st.window_end:
                satisfied.add(vid)
                st.captured_at = t
                if vid in priority_ids:
                    res.priority_captured += 1
                    res.priority_slots += 1
                else:
                    res.bg_captured += 1
                    res.bg_slots += 1
            elif vid in priority_ids:
                res.priority_missed += 1
            else:
                res.bg_missed += 1

    for vid in priority_ids:
        if vid not in satisfied and not videos[vid].has_outcome:
            res.priority_missed += 1
    return res


def main() -> None:
    url = _url()
    if "youtube_radar_restore_check" not in url:
        raise SystemExit("wrong db")
    session = sessionmaker(bind=create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"}))()
    session.execute(text("SET TRANSACTION READ ONLY"))
    ref = _utc(session.scalar(text("SELECT (now() AT TIME ZONE 'utc')")))

    print(f"reference_utc={ref.isoformat()} db=youtube_radar_restore_check")

    # --- 1. Eligibility SQL ---
    elig = session.execute(
        text(
            """
            WITH earliest AS (
              SELECT DISTINCT ON (video_id) video_id, discovered_at, views_at_discovery
              FROM keyword_discovery_hits
              WHERE views_at_discovery IS NOT NULL
              ORDER BY video_id, discovered_at ASC, id ASC
            ),
            day_appearances AS (
              SELECT
                a.report_date,
                a.video_id,
                min(a.source_computed_at) AS first_attention
              FROM daily_intelligence_run_winner_appearances a
              GROUP BY a.report_date, a.video_id
            ),
            day_stats AS (
              SELECT
                da.report_date,
                count(DISTINCT da.video_id) AS unique_appearance_videos,
                count(DISTINCT da.video_id) FILTER (WHERE e.video_id IS NOT NULL) AS with_baseline,
                count(DISTINCT da.video_id) FILTER (
                  WHERE e.video_id IS NOT NULL
                    AND da.first_attention <= e.discovered_at + interval '84 hours'
                    AND da.first_attention >= e.discovered_at + interval '60 hours'
                ) AS window_open_at_first_attention,
                count(DISTINCT da.video_id) FILTER (
                  WHERE e.video_id IS NOT NULL
                    AND da.first_attention > e.discovered_at + interval '84 hours'
                ) AS window_closed_at_first_attention,
                count(DISTINCT da.video_id) FILTER (
                  WHERE e.video_id IS NOT NULL
                    AND da.first_attention < e.discovered_at + interval '60 hours'
                ) AS before_window_at_first_attention,
                count(DISTINCT da.video_id) FILTER (
                  WHERE EXISTS (
                    SELECT 1 FROM video_snapshots vs
                    WHERE vs.video_id = da.video_id AND vs.views IS NOT NULL
                      AND vs.captured_at <= da.first_attention
                      AND vs.captured_at >= e.discovered_at + interval '60 hours'
                      AND vs.captured_at <= e.discovered_at + interval '84 hours'
                  )
                ) AS already_measured_at_first_attention
              FROM day_appearances da
              LEFT JOIN earliest e ON e.video_id = da.video_id
              GROUP BY da.report_date
            ),
            edition AS (
              SELECT report_date, count(DISTINCT video_id) AS edition_unique
              FROM daily_intelligence_report_winner_findings
              GROUP BY report_date
            )
            SELECT ds.*, ed.edition_unique
            FROM day_stats ds
            LEFT JOIN edition ed ON ed.report_date = ds.report_date
            ORDER BY ds.report_date
            """,
        ),
    ).all()
    print("\n=== 1. Attention appearances by report_date (UTC edition day) ===")
    for r in elig:
        print(dict(r._mapping))

    # Discovery-to-first-attention distribution (appearances, ms)
    dist = session.execute(
        text(
            """
            WITH earliest AS (
              SELECT DISTINCT ON (video_id) video_id, discovered_at
              FROM keyword_discovery_hits WHERE views_at_discovery IS NOT NULL
              ORDER BY video_id, discovered_at ASC, id ASC
            ),
            fa AS (
              SELECT video_id, min(source_computed_at) AS first_attention
              FROM daily_intelligence_run_winner_appearances
              GROUP BY video_id
            )
            SELECT
              count(*) AS n,
              round(avg(extract(epoch FROM (f.first_attention - e.discovered_at))/3600.0)::numeric, 2) AS avg_h,
              round(percentile_cont(0.5) WITHIN GROUP (
                ORDER BY extract(epoch FROM (f.first_attention - e.discovered_at))/3600.0
              )::numeric, 2) AS p50_h,
              round(percentile_cont(0.9) WITHIN GROUP (
                ORDER BY extract(epoch FROM (f.first_attention - e.discovered_at))/3600.0
              )::numeric, 2) AS p90_h,
              round(min(extract(epoch FROM (f.first_attention - e.discovered_at))/3600.0)::numeric, 2) AS min_h,
              round(max(extract(epoch FROM (f.first_attention - e.discovered_at))/3600.0)::numeric, 2) AS max_h
            FROM fa f
            JOIN earliest e ON e.video_id = f.video_id
            """,
        ),
    ).one()
    print("\n=== Discovery to first Attention (hours), appearance videos ===")
    print(dict(dist._mapping))

    # Priority pool: eligible (baseline + first_attention <= window_end)
    pool = session.execute(
        text(
            """
            WITH earliest AS (
              SELECT DISTINCT ON (video_id) video_id, discovered_at, views_at_discovery
              FROM keyword_discovery_hits WHERE views_at_discovery IS NOT NULL
              ORDER BY video_id, discovered_at ASC, id ASC
            ),
            fa AS (
              SELECT video_id, min(source_computed_at) AS first_attention
              FROM daily_intelligence_run_winner_appearances
              GROUP BY video_id
            )
            SELECT
              count(*) AS appearance_videos,
              count(*) FILTER (
                WHERE f.first_attention <= e.discovered_at + interval '84 hours'
              ) AS still_measurable_in_principle,
              count(*) FILTER (
                WHERE EXISTS (
                  SELECT 1 FROM video_snapshots vs
                  WHERE vs.video_id = e.video_id AND vs.views IS NOT NULL
                    AND vs.captured_at >= e.discovered_at + interval '60 hours'
                    AND vs.captured_at <= e.discovered_at + interval '84 hours'
                )
              ) AS now_have_in_window_outcome,
              count(*) FILTER (
                WHERE f.first_attention <= e.discovered_at + interval '84 hours'
                  AND NOT EXISTS (
                    SELECT 1 FROM video_snapshots vs
                    WHERE vs.video_id = e.video_id AND vs.views IS NOT NULL
                      AND vs.captured_at >= e.discovered_at + interval '60 hours'
                      AND vs.captured_at <= e.discovered_at + interval '84 hours'
                  )
                  AND e.discovered_at + interval '84 hours' <= (now() AT TIME ZONE 'utc')
              ) AS missed_measurable,
              count(*) FILTER (
                WHERE f.first_attention <= e.discovered_at + interval '84 hours'
                  AND e.discovered_at + interval '84 hours' > (now() AT TIME ZONE 'utc')
              ) AS pending_future
            FROM fa f
            JOIN earliest e ON e.video_id = f.video_id
            """,
        ),
    ).one()
    print("\n=== Historical appearance videos — measurability summary ===")
    print(dict(pool._mapping))

    # Load cycle timestamps
    cycles = [
        _utc(r[0])
        for r in session.execute(
            text("SELECT started_at FROM outcome_capture_cycle_runs ORDER BY started_at ASC"),
        ).all()
    ]
    print(f"\n=== Simulation input: {len(cycles)} historical cycles ===")

    # Build video states for appearance videos + sample background (cap for perf)
    rows = session.execute(
        text(
            """
            WITH earliest AS (
              SELECT DISTINCT ON (video_id) video_id, discovered_at
              FROM keyword_discovery_hits WHERE views_at_discovery IS NOT NULL
              ORDER BY video_id, discovered_at ASC, id ASC
            ),
            pri AS (
              SELECT video_id, min(source_computed_at) AS first_attention
              FROM daily_intelligence_run_winner_appearances GROUP BY video_id
            ),
            edition AS (
              SELECT DISTINCT video_id FROM daily_intelligence_report_winner_findings
            ),
            bg AS (
              SELECT e.video_id, e.discovered_at
              FROM earliest e
              WHERE e.video_id NOT IN (SELECT video_id FROM pri)
                AND e.discovered_at >= '2026-10-01'::timestamptz
                AND e.discovered_at + interval '84 hours' <= (now() AT TIME ZONE 'utc')
              ORDER BY e.discovered_at DESC
              LIMIT 5000
            )
            SELECT 'pri' AS kind, p.video_id, e.discovered_at, p.first_attention,
              (p.video_id IN (SELECT video_id FROM edition)) AS is_edition
            FROM pri p JOIN earliest e ON e.video_id = p.video_id
            UNION ALL
            SELECT 'bg', b.video_id, b.discovered_at, NULL, false FROM bg b
            """,
        ),
    ).all()

    videos: dict[str, VideoState] = {}
    priority_ids: set[str] = set()
    for kind, vid, disc, fa, is_ed in rows:
        ws, we = window_bounds(disc)
        has = session.scalar(
            text(
                """
                SELECT EXISTS (
                  SELECT 1 FROM video_snapshots vs
                  WHERE vs.video_id = :v AND vs.views IS NOT NULL
                    AND vs.captured_at >= :ws AND vs.captured_at <= :we
                )
                """,
            ),
            {"v": vid, "ws": ws, "we": we},
        )
        st = VideoState(
            video_id=vid,
            discovered_at=_utc(disc),
            window_start=ws,
            window_end=we,
            first_attention=_utc(fa) if fa else None,
            is_edition_winner=bool(is_ed),
            is_appearance=(kind == "pri"),
            has_outcome=bool(has),
        )
        if st.first_attention:
            st.eligible_at_attention = st.first_attention <= st.window_end
            st.window_closed_at_attention = st.first_attention > st.window_end
        videos[vid] = st
        if kind == "pri" and st.eligible_at_attention:
            priority_ids.add(vid)

    pri_total = len([v for v in videos.values() if v.is_appearance])
    pri_eligible = len(priority_ids)
    print(f"sim_videos={len(videos)} priority_eligible={pri_eligible} appearance_total={pri_total}")

    # Mark already satisfied from DB as captured at window (don't re-sim)
    for v in videos.values():
        if v.has_outcome:
            priority_ids.discard(v.video_id)

    sim_a = simulate(
        name="A_current_global_sort",
        cycle_times=cycles,
        videos={k: VideoState(**{**v.__dict__}) for k, v in videos.items()},
        priority_ids=set(),
        reserve=None,
        dynamic=False,
    )
    # Fix A: pass all as one pool
    vids_a = {k: VideoState(**{**v.__dict__}) for k, v in videos.items()}
    sim_a = simulate(name="A", cycle_times=cycles, videos=vids_a, priority_ids=set(), reserve=0, dynamic=False)
    # override A selection - when reserve=0 and not dynamic, we need global - patch simulate for reserve=0 meaning all

    def run_a() -> SimResult:
        res = SimResult(name="A_current")
        satisfied = {v.video_id for v in videos.values() if v.has_outcome}
        for t in cycles:
            due = []
            for vid, st in videos.items():
                if vid in satisfied or t < st.window_start or t > st.window_end:
                    continue
                due.append(((st.window_end - t).total_seconds() / 3600.0, vid))
            due.sort()
            for _, vid in due[:BUDGET]:
                satisfied.add(vid)
                res.slots_used += 1
                if vid in priority_ids:
                    res.priority_captured += 1
                else:
                    res.bg_captured += 1
        res.priority_missed = len(priority_ids) - res.priority_captured
        res.cycles = len(cycles)
        return res

    def run_bc(reserve: int, dynamic: bool, label: str) -> SimResult:
        res = SimResult(name=label)
        satisfied = {v.video_id for v in videos.values() if v.has_outcome}
        pri_set = set(priority_ids)
        for t in cycles:
            due_pri, due_bg = [], []
            for vid, st in videos.items():
                if vid in satisfied or t < st.window_start or t > st.window_end:
                    continue
                h = (st.window_end - t).total_seconds() / 3600.0
                if vid in pri_set:
                    due_pri.append((h, vid))
                else:
                    due_bg.append((h, vid))
            due_pri.sort()
            due_bg.sort()
            if dynamic:
                pc = min(len(due_pri), reserve)
                bc = BUDGET - pc
            else:
                pc = min(len(due_pri), reserve)
                bc = BUDGET - pc
            sel = [v for _, v in due_pri[:pc]] + [v for _, v in due_bg[: max(0, bc)]]
            for vid in sel:
                satisfied.add(vid)
                res.slots_used += 1
                if vid in pri_set:
                    res.priority_captured += 1
                    res.priority_slots += 1
                else:
                    res.bg_captured += 1
                    res.bg_slots += 1
        res.priority_missed = len(priority_ids) - res.priority_captured
        res.cycles = len(cycles)
        return res

    ra = run_a()
    rb = run_bc(30, False, "B_reserve_30")
    rc = run_bc(40, True, "C_dynamic_cap_40")

    print("\n=== 2. Counterfactual simulation (assume capture succeeds if selected in-window) ===")
    print("denominator_priority_eligible=", pri_eligible, "already_had_outcome excluded from priority set")
    for r in (ra, rb, rc):
        print(
            f"{r.name}: priority_captured={r.priority_captured} priority_missed={r.priority_missed} "
            f"bg_captured={r.bg_captured} slots={r.slots_used} cycles={r.cycles} "
            f"pri_slots={getattr(r,'priority_slots',0)}",
        )

    # Actual outcomes for priority set
    actual_pri = session.scalar(
        text(
            """
            WITH earliest AS (
              SELECT DISTINCT ON (video_id) video_id, discovered_at
              FROM keyword_discovery_hits WHERE views_at_discovery IS NOT NULL
              ORDER BY video_id, discovered_at ASC, id ASC
            ),
            pri AS (SELECT DISTINCT video_id FROM daily_intelligence_run_winner_appearances)
            SELECT count(*) FILTER (WHERE EXISTS (
              SELECT 1 FROM video_snapshots vs WHERE vs.video_id = p.video_id AND vs.views IS NOT NULL
                AND vs.captured_at BETWEEN e.discovered_at + interval '60 hours'
                                     AND e.discovered_at + interval '84 hours'
            )) FROM pri p JOIN earliest e ON e.video_id = p.video_id
            """,
        ),
    )
    print(f"\nactual_in_window_outcomes_appearance_videos={actual_pri} / {pri_total}")

    # API: 1 unit per video batch in revisit (50 batch) — order of magnitude
    ins_rate = session.scalar(text("SELECT sum(inserted_snapshot_count)::float / nullif(sum(selected_video_count),0) FROM outcome_capture_cycle_runs"))
    print(f"historical_insert_success_rate_selected={round(ins_rate or 0, 3)} source=outcome_capture_cycle_runs")

    session.close()
    print("\nDONE")


if __name__ == "__main__":
    main()
