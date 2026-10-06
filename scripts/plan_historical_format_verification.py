"""Dry-run plan for MEDIUM/LONG format verification via videos.list (Stage 2.1)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv


def _database_url() -> str:
    load_dotenv(ROOT / ".env.docker")
    user = os.environ["RADAR_LOCAL_DB_USER"].strip()
    pw = quote(os.environ["RADAR_LOCAL_DB_PASSWORD"].strip(), safe="")
    return f"postgresql://{user}:{pw}@127.0.0.1:5433/youtube_radar_restore_check"


def main() -> int:
    os.environ["DATABASE_URL"] = _database_url()
    from app.models.db import SessionLocal, engine
    from app.db.migrations import run_startup_migrations
    from app.services.attention_engine_service import compute_attention_engine
    from app.services.attention_engine_types import AttentionEngineConfig
    from app.services.historical_video_format_verification import build_historical_format_verification_plan

    import logging

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    run_startup_migrations(engine)
    engine.echo = False
    session = SessionLocal()
    try:
        result = compute_attention_engine(session, config=AttentionEngineConfig(), source="historical_plan")
        computed_ids = [w.video_id for w in result.video_winners]
        plan = build_historical_format_verification_plan(
            session,
            computed_winner_ids=computed_ids,
        )
        print("historical_format_verification_plan")
        print(f"video_ids={len(plan.video_ids)} api_batches={plan.batch_count}")
        print(
            f"sources persisted_winners={plan.persisted_winner_count} "
            f"computed_winners={plan.computed_winner_count} "
            f"family_reps={plan.family_representative_count}",
        )
        if plan.video_ids:
            print(f"sample_ids={list(plan.video_ids[:8])}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
