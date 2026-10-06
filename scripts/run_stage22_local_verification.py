#!/usr/bin/env python3
"""Stage 2.2: historical videos.list verification + local Attention refresh."""

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
MAX_VERIFICATION_VIDEOS = 300
SUBSCRIBER_BACKFILL_CHANNEL_LIMIT = 500


def _local_database_url() -> str:
    load_dotenv(ROOT / ".env.docker")
    user = os.environ["RADAR_LOCAL_DB_USER"].strip()
    pw = quote(os.environ["RADAR_LOCAL_DB_PASSWORD"].strip(), safe="")
    return f"postgresql://{user}:{pw}@{EXPECTED_HOST}:{EXPECTED_PORT}/{EXPECTED_DB}"


def _assert_database_target(session) -> None:
    from sqlalchemy import text

    db_name = session.scalar(text("SELECT current_database()"))
    if db_name != EXPECTED_DB:
        raise SystemExit(f"database mismatch: got {db_name!r}, expected {EXPECTED_DB!r}")
    url = os.environ.get("DATABASE_URL", "")
    parsed = urlparse(url)
    if parsed.hostname and parsed.hostname not in ("127.0.0.1", "localhost"):
        raise SystemExit(f"host mismatch in DATABASE_URL: {parsed.hostname!r}")
    if parsed.port and parsed.port != EXPECTED_PORT:
        raise SystemExit(f"port mismatch in DATABASE_URL: {parsed.port!r}")


def _merge_reports(into: dict, report) -> None:
    into["api_batch_count"] += report.api_batch_count
    into["confirmed_regular"] += report.confirmed_regular
    into["live_or_broadcast"] += report.live_or_broadcast
    into["missing"] += report.missing
    into["unresolved"] += report.unresolved
    into["medium_long_to_live"] += report.medium_long_to_live
    into["outcomes"].update(report.outcomes_by_video_id)
    into["transitions_to_live"].extend(report.transitions_to_live)


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    local_url = _local_database_url()
    load_dotenv(ROOT / ".env")
    os.environ["DATABASE_URL"] = local_url

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.config import settings
    from app.db.migrations import run_startup_migrations
    from app.integrations.youtube.client import YouTubeApiClient
    from app.integrations.youtube.key_manager import YouTubeApiKeyManager
    from app.models.orm import AttentionRun, Channel, Video
    from app.services.attention_engine_service import compute_attention_engine
    from app.services.attention_engine_types import AttentionEngineConfig
    from app.services.attention_engine_service import attention_window
    from app.services.attention_evidence import load_attention_evidence
    from app.services.attention_read_model import get_latest_attention_run, refresh_attention_engine
    from app.services.historical_video_format_verification import (
        OUTCOME_CONFIRMED_REGULAR,
        build_historical_format_verification_plan,
        verify_video_id_batches,
    )
    from app.services.radar_target_eligibility import (
        REJECTION_UNKNOWN_SUBSCRIBERS,
        radar_target_rejection_reason,
    )
    from datetime import timedelta

    if not settings.youtube_api_keys:
        raise SystemExit("YOUTUBE_API_KEYS missing; cannot call Data API")

    engine = create_engine(local_url, pool_pre_ping=True)
    run_startup_migrations(engine)
    engine.echo = False
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    client = YouTubeApiClient(YouTubeApiKeyManager(settings.youtube_api_keys))

    try:
        _assert_database_target(session)
        print(
            json.dumps(
                {
                    "db_check": {
                        "host": EXPECTED_HOST,
                        "port": EXPECTED_PORT,
                        "database": EXPECTED_DB,
                    },
                },
            ),
        )

        prev_run = get_latest_attention_run(session)
        before = {
            "run_id": prev_run.run_id if prev_run else None,
            "winners": prev_run.winner_count if prev_run else 0,
            "patterns": prev_run.pattern_count if prev_run else 0,
            "families": json.loads(prev_run.notes_json or "{}").get("pattern_family_count")
            if prev_run
            else 0,
            "channels": prev_run.channel_momentum_count if prev_run else 0,
        }

        totals: dict = {
            "api_batch_count": 0,
            "confirmed_regular": 0,
            "live_or_broadcast": 0,
            "missing": 0,
            "unresolved": 0,
            "medium_long_to_live": 0,
            "outcomes": {},
            "transitions_to_live": [],
            "checked_video_ids": [],
        }

        compute0 = compute_attention_engine(session, config=AttentionEngineConfig(), source="stage22_precheck")
        plan = build_historical_format_verification_plan(
            session,
            computed_winner_ids=[w.video_id for w in compute0.video_winners],
        )
        print("initial_plan", {"video_ids": len(plan.video_ids), "batches": plan.batch_count})

        report1 = verify_video_id_batches(session, client, list(plan.video_ids))
        _merge_reports(totals, report1)
        totals["checked_video_ids"] = list(dict.fromkeys([*totals["checked_video_ids"], *plan.video_ids]))
        session.commit()

        compute1 = compute_attention_engine(session, config=AttentionEngineConfig(), source="stage22_post_plan")
        checked = set(totals["checked_video_ids"])
        while len(checked) < MAX_VERIFICATION_VIDEOS:
            extra = [w.video_id for w in compute1.video_winners if w.video_id not in checked]
            if not extra:
                break
            take = min(len(extra), MAX_VERIFICATION_VIDEOS - len(checked))
            batch_ids = extra[:take]
            report_extra = verify_video_id_batches(session, client, batch_ids)
            _merge_reports(totals, report_extra)
            checked.update(batch_ids)
            totals["checked_video_ids"] = list(checked)
            session.commit()
            compute1 = compute_attention_engine(session, config=AttentionEngineConfig(), source="stage22_post_extra")

        publishable = frozenset(
            vid
            for vid, outcome in totals["outcomes"].items()
            if outcome == OUTCOME_CONFIRMED_REGULAR
        )
        compute_final = compute_attention_engine(session, config=AttentionEngineConfig(), source="stage22_pre_publish")
        winner_ids = [w.video_id for w in compute_final.video_winners]
        unverified_winners = [vid for vid in winner_ids if vid not in totals["outcomes"]]
        blocked_winners = [
            vid
            for vid in winner_ids
            if totals["outcomes"].get(vid) not in (None, OUTCOME_CONFIRMED_REGULAR)
        ]
        publishable_winners = [vid for vid in winner_ids if vid in publishable]

        # Subscriber backfill dry-run
        now = compute_final.summary.computed_at
        window_start, window_end = attention_window(now=now, window_hours=24)
        lookback = window_end - timedelta(days=14)
        bundle = load_attention_evidence(
            session,
            window_start=window_start,
            window_end=window_end,
            channel_lookback_start=lookback,
        )
        unknown_channels: list[str] = []
        for rec in bundle.records.values():
            if (
                radar_target_rejection_reason(
                    content_format=rec.video.content_format,
                    channel=rec.channel,
                    latest_snapshot=rec.latest_snapshot,
                )
                != REJECTION_UNKNOWN_SUBSCRIBERS
            ):
                continue
            if rec.video.channel_id:
                unknown_channels.append(rec.video.channel_id)
        unique_unknown_channels = list(dict.fromkeys(unknown_channels))
        backfill_plan = unique_unknown_channels[:SUBSCRIBER_BACKFILL_CHANNEL_LIMIT]
        backfill_batches = (len(backfill_plan) + 49) // 50

        result = refresh_attention_engine(
            session,
            config=AttentionEngineConfig(),
            publishable_winner_video_ids=frozenset(
                vid for vid in winner_ids if vid in publishable
            ),
        )
        session.commit()

        after_run = get_latest_attention_run(session)
        after = {
            "run_id": after_run.run_id if after_run else None,
            "winners": after_run.winner_count if after_run else 0,
            "patterns": after_run.pattern_count if after_run else 0,
            "families": json.loads(after_run.notes_json or "{}").get("pattern_family_count")
            if after_run
            else 0,
            "channels": after_run.channel_momentum_count if after_run else 0,
            "eligibility": json.loads(after_run.notes_json or "{}").get("radar_target_eligibility")
            if after_run
            else {},
            "filter_notes": json.loads(after_run.notes_json or "{}").get("published_winners_filtered")
            if after_run
            else {},
        }

        top10 = []
        for w in result.video_winners[:10]:
            ch = session.get(Channel, w.channel_id)
            vid_row = session.get(Video, w.video_id)
            top10.append(
                {
                    "video_id": w.video_id,
                    "title": w.title,
                    "channel_title": w.channel_title,
                    "subscribers": w.subscribers,
                    "vph": w.vph,
                    "format_outcome": totals["outcomes"].get(w.video_id),
                    "content_format": vid_row.content_format.value if vid_row else None,
                },
            )

        print(
            json.dumps(
                {
                    "verification": {
                        "unique_videos_checked": len(checked),
                        "api_requests_videos_list": totals["api_batch_count"],
                        "confirmed_regular": totals["confirmed_regular"],
                        "live_or_broadcast": totals["live_or_broadcast"],
                        "missing": totals["missing"],
                        "unresolved": totals["unresolved"],
                        "medium_long_to_live": totals["medium_long_to_live"],
                        "transitions_to_live": totals["transitions_to_live"],
                    },
                    "winners_publish": {
                        "computed_before_filter": len(winner_ids),
                        "published": len(result.video_winners),
                        "unverified_still_in_compute": unverified_winners[:20],
                        "blocked_by_format_check": blocked_winners[:20],
                        "all_published_verified_regular": all(
                            totals["outcomes"].get(w.video_id) == OUTCOME_CONFIRMED_REGULAR
                            for w in result.video_winners
                        ),
                        "cap_reached": len(checked) >= MAX_VERIFICATION_VIDEOS,
                    },
                    "subscriber_backfill_dry_run": {
                        "unique_unknown_subscriber_channels": len(unique_unknown_channels),
                        "planned_channels": len(backfill_plan),
                        "planned_channels_list_batches": backfill_batches,
                        "api": "YouTubeApiClient.get_channels (channels.list part=snippet,statistics)",
                        "note": "subscriberCount absent/hidden must not be stored as 0",
                    },
                    "before": before,
                    "after": after,
                    "top10_published_winners": top10,
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
