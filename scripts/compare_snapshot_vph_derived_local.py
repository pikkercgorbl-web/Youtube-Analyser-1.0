#!/usr/bin/env python3
"""Read-only: compare persisted snapshot.vph vs derived measurement on local DB."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

ARTIFACT = ROOT / "artifacts" / "snapshot_vph_derived_compare.json"
FIXED_NOW = datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc)
SAMPLE_LIMIT = 5000


def _legacy_vph(snapshot_vph, views, age_now):
    if snapshot_vph is not None:
        return float(snapshot_vph)
    if views is None or age_now is None or age_now <= 0:
        return None
    return round(float(views) / age_now, 4)


def main() -> int:
    load_dotenv(ROOT / ".env")
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from app.models.db import SessionLocal, engine
    from app.models.orm import Video, VideoSnapshot
    from app.services.monitoring_video_source import _state_from_video
    from app.services.snapshot_measurement import derive_measurement_at_snapshot
    from app.services.video_snapshot_storage import get_latest_snapshots_for_videos

    engine.echo = False
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        from sqlalchemy import func

        latest_subq = (
            select(
                VideoSnapshot.video_id,
                func.max(VideoSnapshot.captured_at).label("max_cap"),
            )
            .group_by(VideoSnapshot.video_id)
            .subquery()
        )
        snap_rows = session.scalars(
            select(VideoSnapshot)
            .join(
                latest_subq,
                (VideoSnapshot.video_id == latest_subq.c.video_id)
                & (VideoSnapshot.captured_at == latest_subq.c.max_cap),
            )
            .where(VideoSnapshot.vph.isnot(None))
            .limit(SAMPLE_LIMIT),
        ).all()
        video_ids = [s.video_id for s in snap_rows]
        latest = {s.video_id: s for s in snap_rows}
        stored_vs_derived = 0
        consumer_changed = 0
        examples = []

        def _vph_close(a, b) -> bool:
            if a is None and b is None:
                return True
            if a is None or b is None:
                return False
            return abs(float(a) - float(b)) <= 1e-4

        for vid in video_ids:
            video = session.get(Video, vid)
            snap = latest.get(vid)
            if video is None or snap is None or snap.vph is None:
                continue
            new_state = _state_from_video(
                video,
                now=FIXED_NOW,
                latest_snapshot=snap,
            )
            age_now = new_state.age_hours
            views = snap.views if snap.views is not None else video.views_count
            legacy_vph = _legacy_vph(snap.vph, views, age_now)
            new_m = derive_measurement_at_snapshot(video=video, snapshot=snap)
            derived_vph = new_m.average_vph
            consumer_vph = new_state.raw_vph
            mismatch_stored = not _vph_close(snap.vph, derived_vph)
            mismatch_consumer = not _vph_close(legacy_vph, consumer_vph)
            if mismatch_stored:
                stored_vs_derived += 1
            if mismatch_consumer:
                consumer_changed += 1
            if mismatch_stored or mismatch_consumer:
                if len(examples) < 10:
                    examples.append(
                        {
                            "video_id": vid,
                            "published_at_source": getattr(video, "published_at_source", None),
                            "published_at": video.published_at.isoformat() if video.published_at else None,
                            "snapshot_published_at": snap.published_at.isoformat() if snap.published_at else None,
                            "views": snap.views,
                            "measured_at": snap.captured_at.isoformat(),
                            "stored_snapshot_vph": snap.vph,
                            "derived_vph": derived_vph,
                            "legacy_consumer_vph": legacy_vph,
                            "new_consumer_vph": consumer_vph,
                            "current_age_hours_at_fixed_now": age_now,
                            "stored_vs_derived_mismatch": mismatch_stored,
                            "consumer_vph_changed": mismatch_consumer,
                        },
                    )
        report = {
            "fixed_now": FIXED_NOW.isoformat(),
            "videos_scanned": len(video_ids),
            "with_latest_snapshot_vph": sum(1 for v in video_ids if latest.get(v) and latest[v].vph is not None),
            "stored_vph_vs_derived_mismatch_count": stored_vs_derived,
            "consumer_vph_changed_count": consumer_changed,
            "derived_vph_diff_count": consumer_changed,
            "examples": examples,
            "note": "Rank changes not computed in this script (read-only sample).",
        }
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps(report, indent=2, default=str))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
