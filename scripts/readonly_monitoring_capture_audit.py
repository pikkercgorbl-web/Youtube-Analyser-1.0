"""Read-only: last N ok monitoring cycles vs snapshots (no writes)."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.models.db import SessionLocal
from app.models.orm import MonitoringCycleRun, MonitoringVideoQueueEntry, VideoSnapshot
from app.services.snapshot_collection_policy import (
    checkpoint_match_window,
    SnapshotCollectionPolicy,
)

POLICY = SnapshotCollectionPolicy()
SOURCE = "monitoring_worker"
LIMIT = 7


def _checkpoint_completed(*, age_hours: float | None, target_cp: int) -> bool | None:
    if age_hours is None:
        return None
    lo, hi = checkpoint_match_window(target_cp, POLICY)
    return lo <= age_hours <= hi


def main() -> int:
    session = SessionLocal()
    try:
        runs = list(
            session.scalars(
                select(MonitoringCycleRun)
                .where(MonitoringCycleRun.cycle_status == "ok")
                .order_by(MonitoringCycleRun.finished_at.desc())
                .limit(LIMIT),
            ).all(),
        )
        runs.reverse()  # chronological

        rows_out: list[dict] = []
        seen_capture_keys: list[tuple[str, int]] = []

        for run in runs:
            run_id = run.run_id
            snaps = list(
                session.scalars(
                    select(VideoSnapshot)
                    .where(
                        VideoSnapshot.source == SOURCE,
                        VideoSnapshot.run_id.like(f"{run_id}:%"),
                    )
                    .order_by(VideoSnapshot.captured_at.asc()),
                ).all(),
            )
            queue = {
                q.video_id: q
                for q in session.scalars(
                    select(MonitoringVideoQueueEntry).where(
                        MonitoringVideoQueueEntry.run_id == run_id,
                    ),
                ).all()
            }

            if not snaps:
                rows_out.append(
                    {
                        "run_id": run_id,
                        "finished_at_utc": run.finished_at.isoformat() if run.finished_at else None,
                        "cycle_summary": {
                            "selected": run.selected_request_count,
                            "inserted": run.inserted_snapshot_count,
                            "due": run.due_count,
                            "overdue": run.overdue_count,
                        },
                        "captures": [],
                    },
                )
                continue

            for snap in snaps:
                meta = snap.raw_metadata or {}
                cp = meta.get("checkpoint_age_hours")
                reason = meta.get("capture_reason") or meta.get("reason")
                if cp is None and ":" in snap.run_id:
                    cp = None
                try:
                    cp_int = int(cp) if cp is not None else None
                except (TypeError, ValueError):
                    cp_int = None

                q = queue.get(snap.video_id)
                due_json = json.loads(q.due_checkpoint_hours_json) if q else []
                overdue_json = json.loads(q.overdue_checkpoint_hours_json) if q else []
                queue_reason = None
                if cp_int is not None:
                    if cp_int in overdue_json:
                        queue_reason = "overdue"
                    elif cp_int in due_json:
                        queue_reason = "due"

                completed = _checkpoint_completed(age_hours=snap.age_hours, target_cp=cp_int) if cp_int else None

                key = (snap.video_id, cp_int or -1)
                repeat_of_prior = key in seen_capture_keys if cp_int is not None else False
                if cp_int is not None:
                    seen_capture_keys.append(key)

                prior_same_cp = list(
                    session.scalars(
                        select(VideoSnapshot)
                        .where(
                            VideoSnapshot.video_id == snap.video_id,
                            VideoSnapshot.source == SOURCE,
                            VideoSnapshot.captured_at < snap.captured_at,
                        )
                        .order_by(VideoSnapshot.captured_at.desc())
                        .limit(20),
                    ).all(),
                )
                prior_completed_same_cp = False
                if cp_int is not None:
                    for p in prior_same_cp:
                        pm = p.raw_metadata or {}
                        if pm.get("checkpoint_age_hours") == cp_int:
                            continue
                        if _checkpoint_completed(age_hours=p.age_hours, target_cp=cp_int):
                            prior_completed_same_cp = True
                            break
                        pcp = pm.get("checkpoint_age_hours")
                        if pcp == cp_int and _checkpoint_completed(age_hours=p.age_hours, target_cp=cp_int):
                            prior_completed_same_cp = True
                            break
                    for p in prior_same_cp:
                        if _checkpoint_completed(age_hours=p.age_hours, target_cp=cp_int):
                            prior_completed_same_cp = True
                            break

                rows_out.append(
                    {
                        "run_id": run_id,
                        "finished_at_utc": run.finished_at.isoformat() if run.finished_at else None,
                        "video_id": snap.video_id,
                        "checkpoint_age_hours": cp_int,
                        "capture_reason": reason or queue_reason,
                        "captured_at_utc": snap.captured_at.isoformat(),
                        "snapshot_age_hours": snap.age_hours,
                        "checkpoint_completed_by_this_snapshot": completed,
                        "prior_snapshot_already_completed_same_checkpoint": prior_completed_same_cp,
                        "repeat_video_checkpoint_vs_earlier_runs_in_window": repeat_of_prior,
                    },
                )

        # flatten per-run for display
        print(json.dumps({"runs_analyzed": len(runs), "detail": rows_out}, indent=2, default=str))

        keys = [
            (r["video_id"], r["checkpoint_age_hours"])
            for r in rows_out
            if r.get("video_id") and r.get("checkpoint_age_hours") is not None
        ]
        unique_keys = set(keys)
        print("\n--- summary ---")
        print(f"capture_rows: {len(keys)}")
        print(f"unique (video_id, checkpoint): {len(unique_keys)}")
        if len(keys) != len(unique_keys):
            from collections import Counter

            c = Counter(keys)
            dupes = {k: v for k, v in c.items() if v > 1}
            print(f"duplicate keys in last {LIMIT} ok runs: {dupes}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
