"""Benchmark keyword performance list evaluation (Stage 1.18B)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

from app.models.db import SessionLocal
from app.models.orm import KeywordDiscoveryHit, TargetKeyword
from app.services.keyword_performance_service import list_keyword_performance


def main() -> int:
    session = SessionLocal()
    try:
        keyword_count = session.scalar(select(func.count()).select_from(TargetKeyword)) or 0
        hit_count = session.scalar(select(func.count()).select_from(KeywordDiscoveryHit)) or 0
        limit = min(100, max(keyword_count, 1))
        start = time.perf_counter()
        result = list_keyword_performance(session, limit=limit)
        elapsed = time.perf_counter() - start
        distinct_videos = sum(i.attributed_video_count or 0 for i in result.items)
        print(f"keywords_evaluated={len(result.items)} limit={limit}")
        print(f"discovery_hit_rows_total={hit_count}")
        print(f"attributed_videos_sum={distinct_videos}")
        print(f"global_breakout_eligible_N={result.context.global_eligible_video_count}")
        print(f"list_runtime_seconds={elapsed:.3f}")
        print(f"evaluated_at={result.context.evaluated_at.isoformat()}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
