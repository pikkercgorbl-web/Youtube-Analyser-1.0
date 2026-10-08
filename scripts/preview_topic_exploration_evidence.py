#!/usr/bin/env python3
"""Read-only preview of topic exploration from persisted DB evidence (no YouTube HTTP)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Preview exploration phrases from DB passes")
    parser.add_argument(
        "--cycle-run-id",
        default=None,
        help="Discovery cycle run_id (default: latest pass cycle)",
    )
    parser.add_argument("--limit-passes", type=int, default=10)
    args = parser.parse_args()

    from sqlalchemy import select

    from app.models.db import SessionLocal
    from app.models.orm import TopicExplorationPass, TopicExplorationVideoObservation
    from app.services.topic_exploration_preview import build_topic_exploration_preview
    from app.services.topic_exploration_types import TopicExplorationScanSummary, TopicExplorationTitleHit

    session = SessionLocal()
    try:
        stmt = select(TopicExplorationPass).order_by(TopicExplorationPass.observed_at.desc())
        if args.cycle_run_id:
            stmt = stmt.where(TopicExplorationPass.cycle_discovery_run_id == args.cycle_run_id)
        passes = list(session.scalars(stmt.limit(args.limit_passes)).all())
        if not passes:
            print(json.dumps({"ok": False, "error": "no_exploration_passes"}, indent=2))
            return 1

        cycle_id = args.cycle_run_id or passes[0].cycle_discovery_run_id
        cycle_passes = [p for p in passes if p.cycle_discovery_run_id == cycle_id]
        scans: list[TopicExplorationScanSummary] = []
        for prow in reversed(cycle_passes):
            obs = list(
                session.scalars(
                    select(TopicExplorationVideoObservation).where(
                        TopicExplorationVideoObservation.pass_id == prow.id,
                    ),
                ).all(),
            )
            hits = tuple(
                TopicExplorationTitleHit(
                    video_id=o.video_id,
                    channel_id=o.channel_id,
                    title=o.title,
                    exploration_query_id=prow.exploration_query_id,
                    exploration_query_text=prow.exploration_query_text,
                    discovery_run_id=prow.pass_discovery_run_id,
                    discovered_at=o.observed_at,
                )
                for o in obs
            )
            scans.append(
                TopicExplorationScanSummary(
                    query_id=prow.exploration_query_id,
                    query_text=prow.exploration_query_text,
                    discovery_run_id=prow.pass_discovery_run_id,
                    started_at=prow.observed_at,
                    finished_at=prow.finished_at,
                    max_pages=prow.pages_scanned,
                    title_hits=hits,
                    status="ok" if prow.status == "ok" else "failed",
                    pages_requested=prow.pages_requested,
                    pages_scanned=prow.pages_scanned,
                    settings_version=prow.settings_version,
                    pass_fingerprint=prow.pass_fingerprint,
                    pass_id=prow.id,
                ),
            )

        preview = build_topic_exploration_preview(
            session,
            discovery_run_id=cycle_id,
            exploration_scans=tuple(scans),
            record_phrase_stats=False,
        )
        out = {
            "ok": True,
            "cycle_discovery_run_id": cycle_id,
            "pass_count": len(scans),
            "proposed": [
                {
                    "phrase": p.phrase,
                    "videos": list(p.distinct_video_ids),
                    "channels": list(p.distinct_channel_ids),
                    "novelty": list(p.novelty_signals),
                    "detail": p.novelty_detail,
                }
                for p in preview.proposed
            ],
            "rejected_sample": [
                {"phrase": r.phrase, "reason": r.reason_code} for r in preview.rejected[:20]
            ],
            "metadata": preview.metadata,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
