#!/usr/bin/env python3
"""One-shot live acceptance for SavedVideo similar watch (real InnerTube). Read-only side effects except watch tables."""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select, text

from app.models.db import SessionLocal, engine
from app.db.migrations import ensure_saved_video_similar_watch_tables
from app.models.orm import (
    KeywordDiscoveryHit,
    SavedVideo,
    SavedVideoSimilarFinding,
    SavedVideoSimilarScan,
    SavedVideoSimilarWatch,
    TargetKeyword,
)
from app.services.saved_video_similar_query_suggest import suggest_similar_search_queries, parse_frozen_json
from app.services.saved_video_similar_watch import (
    confirm_similar_watch_queries,
    execute_similar_watch_scan,
    get_or_create_watch_draft,
    list_findings,
    save_finding_to_saved_research,
)
from app.services.saved_video_similar_watch_config import similar_watch_load_estimate


def _counts(session) -> dict[str, int]:
    return {
        "target_keywords": session.scalar(select(func.count()).select_from(TargetKeyword)) or 0,
        "keyword_discovery_hits": session.scalar(select(func.count()).select_from(KeywordDiscoveryHit)) or 0,
        "similar_scans": session.scalar(select(func.count()).select_from(SavedVideoSimilarScan)) or 0,
        "similar_findings": session.scalar(select(func.count()).select_from(SavedVideoSimilarFinding)) or 0,
    }


def main() -> None:
    ensure_saved_video_similar_watch_tables(engine)
    print("=== load_estimate (after fix) ===")
    print(json.dumps(similar_watch_load_estimate(), indent=2, ensure_ascii=False))

    with SessionLocal() as session:
        before = _counts(session)
        row = session.scalar(
            select(SavedVideo).where(SavedVideo.archived_at.is_(None)).order_by(SavedVideo.id.asc()).limit(1),
        )
        if row is None:
            raise SystemExit("No active SavedVideo in DB")

        frozen = parse_frozen_json(row.frozen_payload_json)
        suggestions = suggest_similar_search_queries(title=row.frozen_title, frozen_payload=frozen)
        queries = suggestions[:3] if len(suggestions) >= 3 else suggestions
        if len(queries) < 2:
            queries = [row.frozen_title[:80], f"{row.frozen_title[:40]} gameplay"]

        print("\n=== SavedVideo ===")
        print("id", row.id, "video_id", row.video_id, "title", row.frozen_title[:120])
        print("confirmed_queries", queries)

        get_or_create_watch_draft(session, saved_video_id=row.id)
        confirm_similar_watch_queries(session, saved_video_id=row.id, queries=queries)
        session.commit()

        t0 = time.perf_counter()
        summary = execute_similar_watch_scan(session, saved_video_id=row.id, trigger="manual")
        session.commit()
        elapsed = time.perf_counter() - t0

        findings, total = list_findings(session, saved_video_id=row.id, limit=50)
        watch = session.get(SavedVideoSimilarWatch, row.id)
        scan = session.get(SavedVideoSimilarScan, summary.scan_id)

        print("\n=== Scan ===")
        print("elapsed_sec", round(elapsed, 2))
        print("queries_attempted", summary.queries_attempted, "queries_failed", summary.queries_failed)
        print("new_findings_count", summary.new_findings_count, "unique_findings_total", total)
        print("display_state", summary.display_state)
        if scan:
            err = json.loads(scan.payload_json or "{}").get("errors") or []
            print("scan_errors_count", len(err))

        print("\n=== First 5 findings (for report) ===")
        for f in findings[:5]:
            p = json.loads(f.payload_json or "{}")
            print(
                json.dumps(
                    {
                        "video_id": f.video_id,
                        "title": p.get("title"),
                        "matched_query": f.matched_query,
                        "views_count": p.get("views_count"),
                        "published_text": p.get("published_text"),
                        "thumbnail_url": bool(p.get("thumbnail_url")),
                        "youtube": f"https://www.youtube.com/watch?v={f.video_id}",
                    },
                    ensure_ascii=False,
                ),
            )

        saved_new = None
        if findings:
            for cand in findings:
                if cand.video_id != row.video_id:
                    res = save_finding_to_saved_research(session, saved_video_id=row.id, finding_id=cand.id)
                    session.commit()
                    saved_new = res.item.video_id
                    print("\n=== Saved finding ===", saved_new, "created", res.created)
                    break

        after = _counts(session)
        print("\n=== Global table deltas (scan must not touch discovery) ===")
        for k in before:
            print(k, before[k], "->", after[k], "delta", after[k] - before[k])

        kw_delta = session.execute(
            text(
                "SELECT COUNT(*) FROM target_keywords WHERE created_at > NOW() - INTERVAL '5 minutes'",
            ),
        ).scalar()
        print("target_keywords_created_last_5min", kw_delta)

        print("\nwatch_status", watch.status if watch else None)
        print("last_scan_at", watch.last_scan_at if watch else None)


if __name__ == "__main__":
    main()
