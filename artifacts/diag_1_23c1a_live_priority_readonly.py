"""Read-only diagnostic: live cycle vs priority dry-run (Stage 1.23C.1A)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

LIVE_RUN = "outcome_20261012T121403Z_7fde4a24"


def _url() -> str:
    u = os.environ.get("DATABASE_URL")
    if u:
        return u
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("no DATABASE_URL")


def main() -> None:
    if "youtube_radar_restore_check" not in _url():
        raise SystemExit("wrong db")
    session = sessionmaker(
        bind=create_engine(_url(), connect_args={"options": "-c default_transaction_read_only=on"}),
    )()
    session.execute(text("SET TRANSACTION READ ONLY"))

    row = session.execute(
        text("SELECT * FROM outcome_capture_cycle_runs WHERE run_id = :r"),
        {"r": LIVE_RUN},
    ).mappings().first()
    print("=== outcome_capture_cycle_runs (live) ===")
    print(dict(row) if row else "NOT FOUND")

    snaps = session.execute(
        text(
            """
            SELECT count(*) AS n,
                   count(DISTINCT video_id) AS uv
            FROM video_snapshots
            WHERE source = 'keyword_outcome_worker'
              AND run_id LIKE :prefix
            """,
        ),
        {"prefix": f"{LIVE_RUN}:%"},
    ).one()
    print("\n=== snapshots run_id prefix match ===")
    print(dict(snaps._mapping))

    di_overlap = session.execute(
        text(
            """
            WITH di AS (SELECT DISTINCT video_id FROM daily_intelligence_run_winner_appearances)
            SELECT count(DISTINCT vs.video_id) AS di_videos_in_run
            FROM video_snapshots vs
            JOIN di ON di.video_id = vs.video_id
            WHERE vs.source = 'keyword_outcome_worker'
              AND vs.run_id LIKE :prefix
            """,
        ),
        {"prefix": f"{LIVE_RUN}:%"},
    ).scalar()
    print(f"di_winner_videos_in_live_snapshots={di_overlap}")

    alt = session.execute(
        text(
            """
            SELECT count(*) FROM video_snapshots
            WHERE source = 'keyword_outcome_worker' AND run_id = :r
            """,
        ),
        {"r": LIVE_RUN},
    ).scalar()
    print(f"snapshots_run_id_exact_match={alt}")

    sample = session.execute(
        text(
            """
            SELECT video_id, run_id, captured_at FROM video_snapshots
            WHERE source = 'keyword_outcome_worker' AND run_id LIKE :prefix
            LIMIT 5
            """,
        ),
        {"prefix": f"{LIVE_RUN}:%"},
    ).all()
    print("sample run_ids:", sample)

    # Replay planner at live started_at vs now
    from app.services.delayed_outcome_capture_config import OutcomeCaptureBudgetPolicy
    from app.services.delayed_outcome_capture_planner import plan_delayed_outcome_capture

    if row:
        started = row["started_at"]
        for label, pri in [("OFF", False), ("ON", True)]:
            plan = plan_delayed_outcome_capture(
                session,
                reference=started,
                budget=OutcomeCaptureBudgetPolicy(di_winner_priority_enabled=pri),
            )
            sel = plan.selected_fetch_candidates
            pri_n = sum(1 for c in sel if c.is_di_winner_priority)
            print(
                f"\nreplay @{started.isoformat()} priority={label}: "
                f"pri_due={plan.selection.priority_due} pri_sel={pri_n} bg_sel={plan.selection.background_selected}",
            )
        ref_now = session.scalar(text("SELECT (now() AT TIME ZONE 'utc')"))
        plan_now = plan_delayed_outcome_capture(
            session,
            reference=ref_now,
            budget=OutcomeCaptureBudgetPolicy(di_winner_priority_enabled=True),
        )
        sel = plan_now.selected_fetch_candidates
        print(
            f"\nreplay @now priority=ON: pri_due={plan_now.selection.priority_due} "
            f"pri_sel={sum(1 for c in sel if c.is_di_winner_priority)} "
            f"bg_sel={plan_now.selection.background_selected}",
        )

    # Would live-selected video_ids (replay OFF) intersect DI?
    if row:
        plan_off = plan_delayed_outcome_capture(
            session,
            reference=row["started_at"],
            budget=OutcomeCaptureBudgetPolicy(di_winner_priority_enabled=False),
        )
        live_ids = {c.video_id for c in plan_off.selected_fetch_candidates}
        di_ids = set(
            session.scalars(text("SELECT DISTINCT video_id FROM daily_intelligence_run_winner_appearances")).all(),
        )
        print(f"\nreplay OFF selected intersect DI: {len(live_ids & di_ids)} videos")
        if live_ids & di_ids:
            print("sample intersect:", list(live_ids & di_ids)[:10])

    session.close()


if __name__ == "__main__":
    main()
