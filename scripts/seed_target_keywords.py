"""Seed target_keywords from data/target_keywords.json.

Run from project root:
    python -m scripts.seed_target_keywords
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import delete, select

from app.models.db import SessionLocal
from app.models.orm import RadarWorkerState, TargetKeyword

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "target_keywords.json"
WORKER_STATE_ROW_ID = 1
MAX_KEYWORD_LENGTH = 256


def load_keywords(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    seen: set[str] = set()
    keywords: list[str] = []

    for category_keywords in payload.values():
        if not isinstance(category_keywords, dict):
            continue
        for english_keyword in category_keywords:
            normalized = english_keyword.strip()
            if not normalized or len(normalized) > MAX_KEYWORD_LENGTH:
                continue
            dedupe_key = normalized.casefold()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            keywords.append(normalized)

    return keywords


def seed() -> int:
    keywords = load_keywords(DATA_PATH)

    db = SessionLocal()
    try:
        db.execute(delete(TargetKeyword))

        state = db.get(RadarWorkerState, WORKER_STATE_ROW_ID)
        if state is None:
            state = RadarWorkerState(
                id=WORKER_STATE_ROW_ID,
                last_target_keyword_id=0,
            )
            db.add(state)
        else:
            state.last_target_keyword_id = 0

        db.add_all(TargetKeyword(keyword=keyword) for keyword in keywords)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return len(keywords)


def main() -> None:
    inserted = seed()
    print(f"Inserted {inserted} target keywords.")


if __name__ == "__main__":
    main()
