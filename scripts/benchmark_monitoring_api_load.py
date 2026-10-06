"""Lightweight timing for monitoring read path (optional ops check)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

from app.models.db import SessionLocal
from app.models.orm import Video, VideoFormat, VideoSnapshot
from app.services.breakout_ranking_service import breakout_fundamental_eligibility, rank_breakout_v1
from app.services.monitoring_api_service import (
    build_active_monitoring_enriched,
    get_monitoring_overview,
    list_monitoring_videos,
)
from app.services.monitoring_tier_budget_policy import MonitoringTierPolicy
from app.services.monitoring_video_source import load_monitored_video_states


def _timed(label: str, fn) -> float:
    start = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - start
    print(f"{label}: {elapsed:.2f}s")
    return elapsed


def main() -> int:
    session = SessionLocal()
    try:
        monitorable = session.scalar(
            select(func.count()).select_from(Video).where(
                Video.content_format.not_in((VideoFormat.SHORT, VideoFormat.LIVE)),
            ),
        )
        snapshots = session.scalar(select(func.count()).select_from(VideoSnapshot))
        print(f"monitorable_videos={monitorable} video_snapshots={snapshots}")

        states = load_monitored_video_states(session)
        tier_cfg = MonitoringTierPolicy()
        ranked = rank_breakout_v1(states, tier_policy=tier_cfg)
        eligible = sum(
            1
            for s in states
            if breakout_fundamental_eligibility(s, max_age_monitoring_hours=tier_cfg.max_age_monitoring_hours)[0]
        )
        active, _, _ = build_active_monitoring_enriched(session)
        print(f"breakout_eligible_count={eligible} breakout_ranked_count={len(ranked)} active_after_caps_count={len(active)}")

        _timed("load_monitored_video_states", lambda: load_monitored_video_states(session))
        _timed("get_monitoring_overview", lambda: get_monitoring_overview(session))
        _timed(
            "list_monitoring_videos sort=priority limit=50",
            lambda: list_monitoring_videos(session, sort="priority", limit=50, offset=0).rows,
        )
        _timed(
            "list_monitoring_videos sort=breakout_v1 limit=50",
            lambda: list_monitoring_videos(session, sort="breakout_v1", limit=50, offset=0),
        )
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
