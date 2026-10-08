#!/usr/bin/env python3
"""Read-only dry-run selection profile on local restore DB (Stage 2)."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

ARTIFACT = ROOT / "artifacts" / "stage2_enrichment_dryrun_profile.json"


def main() -> int:
    load_dotenv(ROOT / ".env")
    from sqlalchemy import event
    from sqlalchemy.orm import sessionmaker

    from app.models.db import SessionLocal, engine
    from app.services.radar_api_budget import count_budget_rows, read_budget_day, BUDGET_KIND_CHANNELS_LIST, BUDGET_KIND_VIDEOS_LIST
    from app.services.radar_enrichment_config import radar_enrichment_settings
    from app.services.radar_enrichment_orchestrator import run_radar_enrichment_pass
    from app.services.radar_enrichment_selection import (
        RadarEnrichmentPassContext,
        select_format_enrichment_video_ids,
        select_subscriber_enrichment_channel_ids,
    )

    engine.echo = False
    queries: list[float] = []

    def _before(conn, cursor, statement, parameters, context, executemany) -> None:
        context._t0 = time.perf_counter()

    def _after(conn, cursor, statement, parameters, context, executemany) -> None:
        t0 = getattr(context, "_t0", None)
        if t0 is not None:
            queries.append(time.perf_counter() - t0)

    event.listen(engine, "before_cursor_execute", _before, retval=False)
    event.listen(engine, "after_cursor_execute", _after, retval=False)

    session = SessionLocal()
    now = datetime.now(timezone.utc)
    try:
        rows_before = count_budget_rows(session)
        ch_before = read_budget_day(session, budget_kind=BUDGET_KIND_CHANNELS_LIST, now=now)
        vid_before = read_budget_day(session, budget_kind=BUDGET_KIND_VIDEOS_LIST, now=now)

        t0 = time.perf_counter()
        sub_ids = select_subscriber_enrichment_channel_ids(
            session,
            limit=radar_enrichment_settings.channel_subscriber_enrichment_pass_limit,
            context=RadarEnrichmentPassContext(pass_sequence=0),
            now=now,
        )
        fmt_ids = select_format_enrichment_video_ids(
            session,
            limit=radar_enrichment_settings.video_format_enrichment_pass_limit,
            context=RadarEnrichmentPassContext(pass_sequence=0),
            now=now,
        )
        sel_ms = (time.perf_counter() - t0) * 1000

        class _Noop:
            def get_channels(self, ids):
                return {}

            def get_videos(self, ids):
                return []

        q_before = len(queries)
        dry = run_radar_enrichment_pass(session, _Noop(), dry_run=True, now=now)
        dry_queries = len(queries) - q_before

        rows_after = count_budget_rows(session)
        ch_after = read_budget_day(session, budget_kind=BUDGET_KIND_CHANNELS_LIST, now=now)
        vid_after = read_budget_day(session, budget_kind=BUDGET_KIND_VIDEOS_LIST, now=now)

        report = {
            "now": now.isoformat(),
            "subscriber_selected": len(sub_ids),
            "format_selected": len(fmt_ids),
            "dry_run_subscriber_planned": dry.subscriber_channels_planned,
            "dry_run_format_planned": dry.format_videos_planned,
            "selection_wall_ms": round(sel_ms, 2),
            "dry_run_sql_queries": dry_queries,
            "ledger_rows_before": rows_before,
            "ledger_rows_after": rows_after,
            "ledger_unchanged": rows_before == rows_after
            and ch_before.id_units_reserved == ch_after.id_units_reserved
            and vid_before.id_units_reserved == vid_after.id_units_reserved,
            "backlog_fraction": radar_enrichment_settings.enrichment_backlog_pass_fraction,
        }
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0
    finally:
        event.remove(engine, "before_cursor_execute", _before)
        event.remove(engine, "after_cursor_execute", _after)
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
