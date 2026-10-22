"""SavedFamily topic query plan tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.models.db import SessionLocal
from app.models.orm import SavedFamily, TargetKeyword
from app.services.saved_family_topic_query_suggest import build_family_topic_query_plan
from app.services.saved_family_topic_watch import family_topic_query_plan_for_saved


def test_id1_no_phonk_or_reddit_in_suggestions():
    session = SessionLocal()
    try:
        saved = session.get(SavedFamily, 1)
        assert saved is not None
        plan = family_topic_query_plan_for_saved(session, saved)
        queries = [s.query.casefold() for s in plan.suggestions]
        assert "doctor phonk" not in queries
        assert "истории reddit 1 час" not in queries
        assert "i will miss you for the rest of my life" not in queries
        assert any("memes then vs now" in q or "мемы" in q for q in queries)
        assert plan.mixed_keyword_provenance
    finally:
        session.close()


def test_heterogeneous_manual_when_no_anchor():
    plan = build_family_topic_query_plan(
        frozen_label="",
        frozen_payload={"keyword_ids": [1, 2], "member_patterns": []},
        keyword_texts_by_id={1: "alpha topic", 2: "unrelated xyz"},
    )
    assert plan.mode in ("manual", "heterogeneous")


def main() -> None:
    test_id1_no_phonk_or_reddit_in_suggestions()
    test_heterogeneous_manual_when_no_anchor()
    print("test_saved_family_topic_query_suggest: OK")


if __name__ == "__main__":
    main()
