"""Read-only audit of keyword provenance for Stage 5 (stdout JSON)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from app.models.db import SessionLocal


def main() -> None:
    session = SessionLocal()
    try:
        out: dict = {}
        out["by_source_lifecycle"] = [
            dict(r._mapping)
            for r in session.execute(
                text(
                    """
                    SELECT source_type, lifecycle_status, COUNT(*) AS n
                    FROM target_keywords
                    GROUP BY source_type, lifecycle_status
                    ORDER BY source_type, lifecycle_status
                    """
                ),
            )
        ]
        out["non_seed_manual_by_source"] = [
            dict(r._mapping)
            for r in session.execute(
                text(
                    """
                    SELECT source_type, COUNT(*) AS n
                    FROM target_keywords
                    WHERE source_type NOT IN ('seed', 'manual')
                    GROUP BY source_type
                    ORDER BY n DESC
                    """
                ),
            )
        ]
        out["parent_linkage"] = [
            dict(r._mapping)
            for r in session.execute(
                text(
                    """
                    SELECT source_type,
                      COUNT(*) FILTER (WHERE parent_keyword_id IS NOT NULL) AS with_parent,
                      COUNT(*) FILTER (WHERE parent_keyword_id IS NULL) AS no_parent
                    FROM target_keywords
                    WHERE source_type NOT IN ('seed', 'manual')
                    GROUP BY source_type
                    """
                ),
            )
        ]
        out["expansion_events"] = [
            dict(r._mapping)
            for r in session.execute(
                text(
                    """
                    SELECT outcome, source_type, COUNT(*) AS n
                    FROM keyword_expansion_events
                    GROUP BY outcome, source_type
                    ORDER BY outcome, source_type
                    """
                ),
            )
        ]
        out["llm_keywords"] = session.execute(
            text("SELECT COUNT(*) AS n FROM target_keywords WHERE source_type = 'llm'"),
        ).scalar()
        out["llm_expansion_events"] = session.execute(
            text("SELECT COUNT(*) AS n FROM keyword_expansion_events WHERE source_type = 'llm'"),
        ).scalar()
        out["expansion_rows_without_created_event_sample"] = [
            dict(r._mapping)
            for r in session.execute(
                text(
                    """
                    SELECT tk.id, tk.keyword, tk.source_type, tk.parent_keyword_id,
                           LEFT(tk.status_reason, 80) AS status_reason
                    FROM target_keywords tk
                    WHERE tk.source_type IN ('suggestion', 'related', 'channel')
                      AND NOT EXISTS (
                        SELECT 1 FROM keyword_expansion_events e
                        WHERE e.created_keyword_id = tk.id AND e.outcome = 'created'
                      )
                    LIMIT 20
                    """
                ),
            )
        ]
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    finally:
        session.close()


if __name__ == "__main__":
    main()
