#!/usr/bin/env python3
"""Re-scan SavedVideo similar watch and print primary/other breakdown."""

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
from app.services.saved_video_similar_query_suggest import suggest_similar_search_queries, parse_frozen_json
from app.services.saved_video_similar_watch import (
    confirm_similar_watch_queries,
    execute_similar_watch_scan,
    get_or_create_watch_draft,
    list_findings_grouped,
)
from app.services.saved_video_similar_relevance import relevance_from_payload


def main() -> None:
    run_startup_migrations(engine)
    saved_video_id = 1
    with SessionLocal() as session:
        from app.models.orm import SavedVideo

        row = session.get(SavedVideo, saved_video_id)
        if row is None:
            raise SystemExit("SavedVideo 1 missing")
        frozen = parse_frozen_json(row.frozen_payload_json)
        queries = suggest_similar_search_queries(title=row.frozen_title, frozen_payload=frozen)
        print("suggested_queries", queries)
        get_or_create_watch_draft(session, saved_video_id=saved_video_id)
        confirm_similar_watch_queries(session, saved_video_id=saved_video_id, queries=queries[: min(3, len(queries))])
        session.commit()
        execute_similar_watch_scan(session, saved_video_id=saved_video_id, trigger="manual")
        session.commit()
        primary, other, total, pt, ot = list_findings_grouped(session, saved_video_id=saved_video_id)
        print("primary_total", pt, "other_total", ot, "all", total)
        from app.services.saved_video_similar_relevance import build_anchor_profile

        anchor = build_anchor_profile(title=row.frozen_title, frozen_payload=frozen)
        print("\n=== first 10 primary ===")
        for f in primary[:10]:
            p = json.loads(f.payload_json or "{}")
            rel = relevance_from_payload(p, anchor, matched_query=f.matched_query)
            print("-", p.get("title", "")[:80])
            print("  query:", f.matched_query)
            print("  why:", rel.why_found or rel.other_reason)
        if not primary:
            print("(none)")
            print("\n=== first 10 other (for visibility) ===")
            for f in other[:10]:
                p = json.loads(f.payload_json or "{}")
                rel = relevance_from_payload(p, anchor, matched_query=f.matched_query)
                print("-", p.get("title", "")[:80])
                print("  reason:", rel.other_reason)


if __name__ == "__main__":
    main()
