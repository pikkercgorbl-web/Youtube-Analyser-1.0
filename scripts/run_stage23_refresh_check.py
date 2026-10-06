#!/usr/bin/env python3
"""Ordinary Attention refresh on local restore DB (default format filter)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv


def main() -> int:
    load_dotenv(ROOT / ".env.docker")
    user = os.environ["RADAR_LOCAL_DB_USER"].strip()
    pw = quote(os.environ["RADAR_LOCAL_DB_PASSWORD"].strip(), safe="")
    local_url = f"postgresql://{user}:{pw}@127.0.0.1:5433/youtube_radar_restore_check"
    os.environ["DATABASE_URL"] = local_url
    load_dotenv(ROOT / ".env")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.migrations import run_startup_migrations
    from app.services.attention_engine_types import AttentionEngineConfig
    from app.services.attention_read_model import get_latest_attention_run, refresh_attention_engine

    engine = create_engine(local_url, pool_pre_ping=True)
    run_startup_migrations(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        before = get_latest_attention_run(session)
        result = refresh_attention_engine(session, config=AttentionEngineConfig())
        session.commit()
        after = get_latest_attention_run(session)
        print(
            json.dumps(
                {
                    "before_run_id": before.run_id if before else None,
                    "before_winners": before.winner_count if before else None,
                    "after_run_id": after.run_id if after else None,
                    "after_winners": after.winner_count if after else None,
                    "filter_notes": json.loads(after.notes_json).get("published_winners_filtered")
                    if after
                    else None,
                    "computed_winners": len(result.video_winners),
                },
                indent=2,
            ),
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
