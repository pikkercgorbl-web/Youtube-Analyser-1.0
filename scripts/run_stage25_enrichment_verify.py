#!/usr/bin/env python3
"""Single live enrichment pass + dry-run replay on restore DB (no workers)."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

EXPECTED_HOST = "127.0.0.1"
EXPECTED_PORT = 5433
EXPECTED_DB = "youtube_radar_restore_check"
ARTIFACT = ROOT / "artifacts" / "stage25_enrichment_verify.json"
PASS_SEQUENCE = 1


def _local_database_url() -> str:
    load_dotenv(ROOT / ".env.docker")
    user = os.environ["RADAR_LOCAL_DB_USER"].strip()
    pw = quote(os.environ["RADAR_LOCAL_DB_PASSWORD"].strip(), safe="")
    return f"postgresql://{user}:{pw}@{EXPECTED_HOST}:{EXPECTED_PORT}/{EXPECTED_DB}"


def _assert_engine_url(engine) -> None:
    url = str(engine.url)
    parsed = urlparse(url)
    if parsed.hostname not in (EXPECTED_HOST, "localhost"):
        raise SystemExit(f"engine host mismatch: {parsed.hostname!r}")
    if parsed.port not in (EXPECTED_PORT, None):
        raise SystemExit(f"engine port mismatch: {parsed.port!r}")
    db = (parsed.path or "").lstrip("/")
    if db != EXPECTED_DB:
        raise SystemExit(f"engine database mismatch: {db!r}")


def _ledger_snapshot(session, now: datetime) -> dict:
    from app.services.radar_api_budget import (
        BUDGET_KIND_CHANNELS_LIST,
        BUDGET_KIND_VIDEOS_LIST,
        budget_day_status,
        remaining_id_units,
        utc_calendar_day,
    )
    from app.services.radar_enrichment_config import radar_enrichment_settings
    from app.services.unknown_format_enrichment_config import unknown_format_enrichment_settings

    day = utc_calendar_day(now)
    ch_row = budget_day_status(session, budget_kind=BUDGET_KIND_CHANNELS_LIST, now=now)
    vid_row = budget_day_status(session, budget_kind=BUDGET_KIND_VIDEOS_LIST, now=now)
    ch_daily = radar_enrichment_settings.channel_subscriber_enrichment_daily_limit
    vid_daily = unknown_format_enrichment_settings.unknown_format_enrichment_daily_video_limit
    return {
        "utc_day": str(day),
        "channels_list": {
            "reserved": ch_row.id_units_reserved,
            "http_requests": ch_row.http_requests,
            "remaining": remaining_id_units(
                session,
                budget_kind=BUDGET_KIND_CHANNELS_LIST,
                daily_limit=ch_daily,
                now=now,
            ),
        },
        "videos_list": {
            "reserved": vid_row.id_units_reserved,
            "http_requests": vid_row.http_requests,
            "remaining": remaining_id_units(
                session,
                budget_kind=BUDGET_KIND_VIDEOS_LIST,
                daily_limit=vid_daily,
                now=now,
            ),
        },
    }


def _planned_ids(session, *, pass_sequence: int, now: datetime) -> dict:
    from app.services.radar_api_budget import BUDGET_KIND_CHANNELS_LIST, BUDGET_KIND_VIDEOS_LIST, remaining_id_units
    from app.services.radar_enrichment_config import radar_enrichment_settings
    from app.services.radar_enrichment_selection import (
        RadarEnrichmentPassContext,
        select_format_enrichment_video_ids,
        select_subscriber_enrichment_channel_ids,
    )
    from app.services.unknown_format_enrichment_config import unknown_format_enrichment_settings

    ctx = RadarEnrichmentPassContext(pass_sequence=pass_sequence)
    ch_limit = min(
        radar_enrichment_settings.channel_subscriber_enrichment_pass_limit,
        remaining_id_units(
            session,
            budget_kind=BUDGET_KIND_CHANNELS_LIST,
            daily_limit=radar_enrichment_settings.channel_subscriber_enrichment_daily_limit,
            now=now,
        ),
    )
    vid_limit = min(
        radar_enrichment_settings.video_format_enrichment_pass_limit,
        remaining_id_units(
            session,
            budget_kind=BUDGET_KIND_VIDEOS_LIST,
            daily_limit=unknown_format_enrichment_settings.unknown_format_enrichment_daily_video_limit,
            now=now,
        ),
    )
    return {
        "channels": select_subscriber_enrichment_channel_ids(session, limit=ch_limit, context=ctx, now=now),
        "videos": select_format_enrichment_video_ids(session, limit=vid_limit, context=ctx, now=now),
    }


def main() -> int:
    local_url = _local_database_url()
    load_dotenv(ROOT / ".env")
    os.environ["DATABASE_URL"] = local_url

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.api.deps import get_youtube_client
    from app.core.config import settings
    from app.db.migrations import run_startup_migrations
    from app.services.radar_enrichment_orchestrator import run_radar_enrichment_pass
    from app.services.radar_enrichment_selection import RadarEnrichmentPassContext

    if not settings.youtube_api_keys:
        raise SystemExit("YOUTUBE_API_KEYS required for live pass")

    now = datetime.now(timezone.utc)
    report: dict = {"started_at": now.isoformat(), "pass_sequence": PASS_SEQUENCE}

    engine = create_engine(local_url, pool_pre_ping=True)
    _assert_engine_url(engine)
    run_startup_migrations(engine)

    Session = sessionmaker(bind=engine)
    client = get_youtube_client()

    session = Session()
    try:
        _assert_engine_url(session.get_bind())
        ledger0 = _ledger_snapshot(session, now)
        planned0 = _planned_ids(session, pass_sequence=PASS_SEQUENCE, now=now)
        t0 = time.perf_counter()
        dry = run_radar_enrichment_pass(
            session,
            client,
            context=RadarEnrichmentPassContext(pass_sequence=PASS_SEQUENCE),
            dry_run=True,
            now=now,
        )
        session.rollback()
        session.expire_all()
        planned_after_dry = _planned_ids(session, pass_sequence=PASS_SEQUENCE, now=now)
        report["dry_run_before_live"] = {
            "seconds": round(time.perf_counter() - t0, 3),
            "ledger": ledger0,
            "planned": planned0,
            "planned_after_dry_unchanged": planned0 == planned_after_dry,
            "pass_report": asdict(dry),
        }
    finally:
        session.close()

    session = Session()
    try:
        ledger_pre = _ledger_snapshot(session, now)
        planned_live = _planned_ids(session, pass_sequence=PASS_SEQUENCE, now=now)
        t1 = time.perf_counter()
        live = run_radar_enrichment_pass(
            session,
            client,
            context=RadarEnrichmentPassContext(pass_sequence=PASS_SEQUENCE),
            dry_run=False,
            now=now,
        )
        session.commit()
        ledger_post = _ledger_snapshot(session, now)
        processed = [
            o
            for batch in (live.notes.get("subscriber_batches") or [])
            for o in (batch.get("outcomes") or [])
        ]
        report["live_pass"] = {
            "seconds": round(time.perf_counter() - t1, 3),
            "ledger_before": ledger_pre,
            "ledger_after": ledger_post,
            "planned": planned_live,
            "pass_report": asdict(live),
            "subscriber_outcomes_by_reason": _count_by(processed, "reason"),
            "subscriber_outcomes_by_api_status": _count_by(processed, "api_status"),
            "per_channel_outcomes": processed,
        }
    finally:
        session.close()

    session = Session()
    try:
        planned2 = _planned_ids(session, pass_sequence=PASS_SEQUENCE, now=now)
        t2 = time.perf_counter()
        dry2 = run_radar_enrichment_pass(
            session,
            client,
            context=RadarEnrichmentPassContext(pass_sequence=PASS_SEQUENCE),
            dry_run=True,
            now=now,
        )
        session.rollback()
        live_ids = {o["channel_id"] for o in report["live_pass"]["per_channel_outcomes"]}
        overlap = sorted(set(planned2["channels"]) & live_ids)
        report["dry_run_after_live"] = {
            "seconds": round(time.perf_counter() - t2, 3),
            "planned": planned2,
            "overlap_with_live_channel_ids": overlap,
            "no_immediate_channel_repick": len(overlap) == 0,
            "pass_report": asdict(dry2),
        }
    finally:
        session.close()

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0


def _count_by(rows: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        val = str(row.get(key) or "unknown")
        out[val] = out.get(val, 0) + 1
    return out


if __name__ == "__main__":
    raise SystemExit(main())
