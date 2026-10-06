"""Seed test Postgres DB with minimal Attention snapshot for browser smoke."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.services.attention_read_model import persist_attention_result
from scripts.test_observation_readiness_e2e import FAMILY_KEY, _reset, _result

UTC = timezone.utc


def main() -> None:
    url = os.environ.get("SAVED_TOPICS_POSTGRES_TEST_URL", "").strip() or os.environ.get("DATABASE_URL", "").strip()
    if not url or "test" not in url.lower():
        raise SystemExit("Set SAVED_TOPICS_POSTGRES_TEST_URL or DATABASE_URL to test database")
    engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    _reset(session)
    persist_attention_result(session, _result(run_id="browser_smoke_run"), run_id="browser_smoke_run")
    session.commit()
    session.close()
    print(json.dumps({"family_key": FAMILY_KEY, "run_id": "browser_smoke_run"}))


if __name__ == "__main__":
    main()
