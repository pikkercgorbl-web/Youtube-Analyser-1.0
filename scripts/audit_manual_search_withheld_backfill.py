"""Read-only audit: legacy manual-search rows vs automatic_monitoring_withheld backfill safety."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

from app.models.db import SessionLocal
from app.models.orm import KeywordDiscoveryHit, SavedVideo, Video

MANUAL_SEARCH_SAVE_SOURCE = "manual_search"


def _saved_from_manual(row: SavedVideo) -> bool:
    try:
        payload = json.loads(row.frozen_payload_json or "{}")
    except json.JSONDecodeError:
        return False
    return (payload.get("context") or {}).get("saved_from") == MANUAL_SEARCH_SAVE_SOURCE


def main() -> None:
    session = SessionLocal()
    try:
        saved_rows = session.scalars(select(SavedVideo)).all()
        manual_bookmarks = [row for row in saved_rows if _saved_from_manual(row)]
        ambiguous = 0
        for row in manual_bookmarks:
            video = session.get(Video, row.video_id)
            if video is None:
                continue
            if not video.automatic_monitoring_withheld:
                ambiguous += 1

        hit_handoff = session.scalar(
            select(func.count())
            .select_from(KeywordDiscoveryHit)
            .where(KeywordDiscoveryHit.persisted_for_monitoring.is_(True)),
        )
        print(
            json.dumps(
                {
                    "manual_search_saved_video_rows": len(manual_bookmarks),
                    "ambiguous_legacy_candidates_withheld_false": ambiguous,
                    "note": (
                        "No automatic backfill is performed. "
                        "saved_from alone is insufficient to prove Video was created by manual save."
                    ),
                    "discovery_handoff_rows_persisted_for_monitoring": int(hit_handoff or 0),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
