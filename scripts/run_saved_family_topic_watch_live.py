"""Live topic-watch scan using verified query set (does not rewrite confirmed queries in DB)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.models.db import SessionLocal
from app.models.orm import SavedFamily, SavedFamilyTopicFinding
from app.services.saved_family_topic_watch import (
    execute_family_topic_watch_scan,
    family_topic_query_plan_for_saved,
)


def main() -> None:
    family_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    session = SessionLocal()
    try:
        family = session.get(SavedFamily, family_id)
        if family is None:
            raise SystemExit(f"Saved family id={family_id} not found")

        plan = family_topic_query_plan_for_saved(session, family)
        queries = [item.query for item in plan.suggestions]
        if not queries and plan.directions:
            queries = [s.query for s in plan.directions[0].suggestions]
        if not queries:
            raise SystemExit(f"No verified queries for family {family_id}: {plan.message}")

        print("Verified queries for live scan (DB confirmed queries unchanged):")
        for q in queries:
            print(" -", q)

        started = time.perf_counter()
        summary = execute_family_topic_watch_scan(
            session,
            saved_family_id=family_id,
            trigger="manual",
            queries_to_run=queries,
        )
        session.commit()
        elapsed = time.perf_counter() - started

        # Read only findings touched by these queries in this scan (approx: filter by matched_query)
        qset = {q.casefold() for q in queries}
        findings = session.scalars(
            select(SavedFamilyTopicFinding)
            .where(SavedFamilyTopicFinding.saved_family_id == family_id)
            .order_by(SavedFamilyTopicFinding.last_found_at.desc()),
        ).all()
        scan_findings = [f for f in findings if (f.matched_query or "").casefold() in qset]
        titles = []
        for f in scan_findings[:10]:
            try:
                payload = json.loads(f.payload_json or "{}")
            except json.JSONDecodeError:
                payload = {}
            titles.append({"title": str(payload.get("title") or f.video_id), "query": f.matched_query})

        report = {
            "saved_family_id": family_id,
            "topic_label": family.frozen_label,
            "anchor_label": plan.anchor_label,
            "verified_queries": queries,
            "plan_mode": plan.mode,
            "duration_seconds": round(elapsed, 2),
            "scan": {
                "queries_attempted": summary.queries_attempted,
                "queries_failed": summary.queries_failed,
                "new_findings_count": summary.new_findings_count,
            },
            "unique_findings_matching_verified_queries": len(scan_findings),
            "first_10_titles": titles,
            "note": "Titles are InnerTube hits for verified queries only; thematic fit is manual.",
        }
        out = ROOT / "artifacts" / "saved_family_topic_watch_live_report.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        session.close()


if __name__ == "__main__":
    main()
