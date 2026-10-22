"""Before/after style report of topic query plans for saved families."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.models.db import SessionLocal
from app.models.orm import SavedFamily
from app.services.saved_family_topic_watch import family_topic_query_plan_for_saved

OLD_ID1 = [
    "memes then vs now died",
    "doctor phonk",
    "истории reddit 1 час",
    "мемы тогда и сейчас",
    "i will miss you for the rest of my life",
]


def main() -> None:
    session = SessionLocal()
    report: dict = {"families": [], "old_id1_queries": OLD_ID1}
    try:
        rows = session.scalars(select(SavedFamily).order_by(SavedFamily.id)).all()
        for saved in rows:
            plan = family_topic_query_plan_for_saved(session, saved)
            report["families"].append(
                {
                    "id": saved.id,
                    "label": saved.frozen_label,
                    "mode": plan.mode,
                    "message": plan.message,
                    "mixed_keyword_provenance": plan.mixed_keyword_provenance,
                    "suggestions": [
                        {
                            "query": s.query,
                            "source_type": s.source_type,
                            "source_explanation": s.source_explanation,
                        }
                        for s in plan.suggestions
                    ],
                    "directions": [
                        {
                            "direction_id": d.direction_id,
                            "label": d.label,
                            "queries": [s.query for s in d.suggestions],
                        }
                        for d in plan.directions
                    ],
                },
            )
    finally:
        session.close()
    out = ROOT / "artifacts" / "saved_family_topic_query_plan_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
