"""Materialize keyword performance read model (Stage 1.20E.4)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.db import SessionLocal
from app.services.keyword_performance_read_model import refresh_keyword_performance_read_model


def main() -> int:
    session = SessionLocal()
    try:
        run_id, rows = refresh_keyword_performance_read_model(session)
        session.commit()
        print(f"keyword_performance_read_model run_id={run_id} rows={rows}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
