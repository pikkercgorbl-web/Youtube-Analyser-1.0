#!/usr/bin/env python3
"""Live similar-watch scan for 3 SavedVideos; per-scan stats only."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.migrations import run_startup_migrations
from app.models.db import SessionLocal, engine
from app.models.orm import SavedVideo
from app.services.saved_video_similar_query_suggest import parse_frozen_json, suggest_similar_search_queries
from app.services.saved_video_similar_watch import (
    confirm_similar_watch_queries,
    execute_similar_watch_scan,
    get_or_create_watch_draft,
    summarize_scan_findings,
)

TOPIC_IDS = (1, 4, 9)


def _classification_errors(summary: dict) -> list[dict]:
    """Heuristic: primary without strong why, or other with 2+ subject-like overlap in title."""
    errors: list[dict] = []
    for item in summary["primary"]:
        if not item.get("why_found"):
            errors.append(
                {
                    "kind": "primary_without_why",
                    "title": item.get("title"),
                    "tier": "primary",
                },
            )
    for item in summary["other"][:30]:
        title = str(item.get("title") or "").lower()
        if "grain cart" in title or "tesla roadster" in title or "moldboard plow" in title:
            errors.append(
                {
                    "kind": "likely_should_be_primary",
                    "title": item.get("title"),
                    "tier": "other",
                    "reason": item.get("other_reason"),
                },
            )
    for item in summary["primary"]:
        title = str(item.get("title") or "").lower()
        if any(x in title for x in ("con artist", "satisfactory", "shopping cart", "warmup")):
            errors.append(
                {
                    "kind": "likely_should_be_other",
                    "title": item.get("title"),
                    "tier": "primary",
                    "why": item.get("why_found"),
                },
            )
    return errors[:5]


def main() -> None:
    run_startup_migrations(engine)
    reports: list[dict] = []
    with SessionLocal() as session:
        for sid in TOPIC_IDS:
            row = session.get(SavedVideo, sid)
            if row is None:
                continue
            frozen = parse_frozen_json(row.frozen_payload_json)
            suggestions = suggest_similar_search_queries(title=row.frozen_title, frozen_payload=frozen)
            queries = suggestions[: min(3, len(suggestions))]
            get_or_create_watch_draft(session, saved_video_id=sid)
            confirm_similar_watch_queries(session, saved_video_id=sid, queries=queries)
            session.commit()
            summary_scan = execute_similar_watch_scan(session, saved_video_id=sid, trigger="manual")
            session.commit()
            scan_stats = summarize_scan_findings(
                session,
                saved_video_id=sid,
                scan_id=summary_scan.scan_id,
            )
            errors = _classification_errors(scan_stats)
            reports.append(
                {
                    "saved_video_id": sid,
                    "title": row.frozen_title,
                    "suggested_queries": suggestions,
                    "confirmed_queries": queries,
                    "scan_id": summary_scan.scan_id,
                    "queries_attempted": summary_scan.queries_attempted,
                    "queries_failed": summary_scan.queries_failed,
                    "unique_videos_this_scan": scan_stats["unique_videos"],
                    "primary_this_scan": scan_stats["primary_count"],
                    "other_this_scan": scan_stats["other_count"],
                    "first_10_primary": scan_stats["primary"][:10],
                    "classification_errors_sample": errors,
                },
            )
    out = Path(ROOT / "artifacts" / "multi_topic_similar_watch_live.json")
    out.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    for r in reports:
        print(
            f"id={r['saved_video_id']} unique={r['unique_videos_this_scan']} "
            f"primary={r['primary_this_scan']} other={r['other_this_scan']}",
        )


if __name__ == "__main__":
    main()
