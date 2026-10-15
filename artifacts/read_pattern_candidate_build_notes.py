"""Read pattern_candidate_build from latest attention_runs.notes_json."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text


def main() -> None:
    u = os.environ.get("DATABASE_URL", "").strip()
    if not u:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                u = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not u:
        raise SystemExit("DATABASE_URL required")
    engine = create_engine(u)
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT run_id, computed_at, notes_json FROM attention_runs "
                "ORDER BY computed_at DESC LIMIT 1",
            ),
        ).fetchone()
    notes = json.loads(row.notes_json or "{}")
    pcb = notes.get("pattern_candidate_build")
    print(
        json.dumps(
            {
                "run_id": row.run_id,
                "computed_at": str(row.computed_at),
                "pattern_candidate_build": pcb,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


if __name__ == "__main__":
    main()
