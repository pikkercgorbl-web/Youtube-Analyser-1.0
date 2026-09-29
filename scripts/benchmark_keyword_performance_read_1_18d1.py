"""Benchmark keyword performance read modes (Stage 1.18D1)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import event, func, select

from app.models.db import SessionLocal
from app.models.orm import KeywordDiscoveryHit, TargetKeyword
from app.services.keyword_performance_profiling import profile_list_keyword_performance
from app.services.keyword_performance_service import list_keyword_performance


def _count_queries(session, fn) -> tuple[int, object]:
    engine = session.get_bind()
    count = 0

    def before_cursor_execute(*_args, **_kwargs) -> None:
        nonlocal count
        count += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute, retval=False)
    try:
        start = time.perf_counter()
        result = fn()
        elapsed = time.perf_counter() - start
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    return count, {"elapsed_seconds": round(elapsed, 4), "result": result}


def main() -> int:
    session = SessionLocal()
    report: dict = {"schema": "1.18D1"}
    try:
        keyword_count = int(session.scalar(select(func.count()).select_from(TargetKeyword)) or 0)
        hit_count = int(session.scalar(select(func.count()).select_from(KeywordDiscoveryHit)) or 0)
        limit = min(100, max(keyword_count, 1))
        report["dataset"] = {"keyword_count": keyword_count, "hit_count": hit_count, "limit": limit}

        modes = {
            "A_base_only": {"include_breakout": False, "include_delayed": False},
            "B_base_breakout": {"include_breakout": True, "include_delayed": False},
            "C_base_delayed": {"include_breakout": False, "include_delayed": True},
            "D_full": {"include_breakout": True, "include_delayed": True},
        }
        benchmarks: dict = {}
        for label, flags in modes.items():
            q, payload = _count_queries(
                session,
                lambda flags=flags: list_keyword_performance(session, limit=limit, **flags),
            )
            result = payload["result"]
            benchmarks[label] = {
                **flags,
                "runtime_seconds": payload["elapsed_seconds"],
                "sql_query_count": q,
                "keywords_returned": len(result.items),
                "global_eligible_video_count": result.context.global_eligible_video_count,
                "attributed_videos_sum": sum(i.attributed_video_count or 0 for i in result.items),
            }
        report["benchmarks"] = benchmarks

        profile, _ = profile_list_keyword_performance(
            session,
            limit=limit,
            include_breakout=True,
            include_delayed=True,
        )
        report["profile_full"] = {
            "phases_seconds": profile.phases_seconds,
            "sql_query_count": profile.sql_query_count,
            "row_counts": profile.row_counts,
        }

        out = ROOT / "artifacts" / "keyword_performance_read_benchmark_1_18d1.json"
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
