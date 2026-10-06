#!/usr/bin/env python3
"""Stage 2.3: subscriber backfill + post-backfill attention compute (local restore DB)."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

EXPECTED_HOST = "127.0.0.1"
EXPECTED_PORT = 5433
EXPECTED_DB = "youtube_radar_restore_check"
BACKFILL_LIMIT = 500


def _local_database_url() -> str:
    load_dotenv(ROOT / ".env.docker")
    user = os.environ["RADAR_LOCAL_DB_USER"].strip()
    pw = quote(os.environ["RADAR_LOCAL_DB_PASSWORD"].strip(), safe="")
    return f"postgresql://{user}:{pw}@{EXPECTED_HOST}:{EXPECTED_PORT}/{EXPECTED_DB}"


def _assert_db(session) -> None:
    from sqlalchemy import text

    db = session.scalar(text("SELECT current_database()"))
    if db != EXPECTED_DB:
        raise SystemExit(f"database mismatch: {db!r}")
    parsed = urlparse(os.environ["DATABASE_URL"])
    if parsed.hostname not in (None, "127.0.0.1", "localhost"):
        raise SystemExit(f"host mismatch: {parsed.hostname!r}")


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    local_url = _local_database_url()
    load_dotenv(ROOT / ".env")
    os.environ["DATABASE_URL"] = local_url

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.core.config import settings
    from app.db.migrations import run_startup_migrations
    from app.integrations.youtube.client import YouTubeApiClient
    from app.integrations.youtube.key_manager import YouTubeApiKeyManager
    from app.models.orm import Video
    from app.services.attention_engine_service import compute_attention_engine
    from app.services.attention_engine_types import AttentionEngineConfig
    from app.services.channel_subscriber_backfill import (
        run_subscriber_backfill,
        select_unknown_subscriber_channel_ids,
    )
    from app.services.radar_target_eligibility import summarize_video_eligibility
    from app.services.attention_evidence import load_attention_evidence
    from app.services.attention_engine_service import attention_window
    from datetime import timedelta
    from app.services.video_format_api_verification import load_api_format_confirmed_video_ids

    if not settings.youtube_api_keys:
        raise SystemExit("YOUTUBE_API_KEYS required")

    engine = create_engine(local_url, pool_pre_ping=True)
    run_startup_migrations(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    client = YouTubeApiClient(YouTubeApiKeyManager(settings.youtube_api_keys))

    try:
        _assert_db(session)

        before = compute_attention_engine(session, config=AttentionEngineConfig(), source="stage23_before")
        ws, we = before.summary.window_start, before.summary.window_end
        bundle_before = load_attention_evidence(
            session,
            window_start=ws,
            window_end=we,
            channel_lookback_start=we - timedelta(days=14),
        )
        stats_before = summarize_video_eligibility(
            [(r.video, r.channel, r.latest_snapshot) for r in bundle_before.records.values()],
        )

        channel_ids = select_unknown_subscriber_channel_ids(
            session,
            limit=BACKFILL_LIMIT,
            window_start=ws,
            window_end=we,
        )
        backfill = run_subscriber_backfill(session, client, channel_ids)
        session.commit()

        after = compute_attention_engine(session, config=AttentionEngineConfig(), source="stage23_after")
        bundle_after = load_attention_evidence(
            session,
            window_start=after.summary.window_start,
            window_end=after.summary.window_end,
            channel_lookback_start=after.summary.window_end - timedelta(days=14),
        )
        stats_after = summarize_video_eligibility(
            [(r.video, r.channel, r.latest_snapshot) for r in bundle_after.records.values()],
        )

        confirmed = load_api_format_confirmed_video_ids(session)
        unverified_winners = [
            w.video_id
            for w in after.video_winners
            if w.video_id not in confirmed
        ]

        top10 = []
        for w in after.video_winners[:10]:
            top10.append(
                {
                    "video_id": w.video_id,
                    "title": w.title,
                    "channel_title": w.channel_title,
                    "subscribers": w.subscribers,
                    "vph": w.vph,
                    "format_confirmed": w.video_id in confirmed,
                },
            )

        stream_unique = after.summary.notes.get("radar_target_eligibility_unique", {}).get("stream", {})

        print(
            json.dumps(
                {
                    "backfill": {
                        "planned": backfill.planned_channels,
                        "api_batches": backfill.api_batch_count,
                        "known": backfill.known,
                        "hidden": backfill.hidden,
                        "missing": backfill.missing,
                        "failed": backfill.failed,
                        "known_zero": backfill.known_zero,
                    },
                    "eligibility_before": stats_before.to_dict(),
                    "eligibility_after": stats_after.to_dict(),
                    "eligible_delta": stats_after.eligible - stats_before.eligible,
                    "over_limit_after": stats_after.rejections.get("over_subscriber_limit", 0),
                    "stream_explanation": stream_unique,
                    "unverified_winner_count": len(unverified_winners),
                    "unverified_winner_sample": unverified_winners[:15],
                    "top10_compute_winners": top10,
                },
                indent=2,
                default=str,
            ),
        )
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
