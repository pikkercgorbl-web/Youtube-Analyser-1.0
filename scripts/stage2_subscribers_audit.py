"""Classify unknown_subscribers causes on local restore DB (Stage 2.1, no network)."""

from __future__ import annotations

import os
import sys
from collections import Counter
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
    import logging

    from datetime import timedelta

    from sqlalchemy import select

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    from app.models.db import SessionLocal
    from app.models.orm import Channel, Video, VideoFormat, VideoSnapshot
    from app.services.attention_engine_service import attention_window, compute_attention_engine
    from app.services.attention_engine_types import AttentionEngineConfig
    from app.services.metrics import utc_now
    from app.services.radar_target_eligibility import (
        REJECTION_UNKNOWN_SUBSCRIBERS,
        radar_target_rejection_reason,
        resolve_known_subscribers,
    )
    from app.services.video_snapshot_storage import get_latest_snapshots_for_videos

    session = SessionLocal()
    try:
        now = utc_now()
        window_start, window_end = attention_window(now=now, window_hours=24)
        causes = Counter()
        examples: list[dict] = []

        from app.services.attention_evidence import load_attention_evidence

        lookback = window_end - timedelta(days=14)
        bundle = load_attention_evidence(
            session,
            window_start=window_start,
            window_end=window_end,
            channel_lookback_start=lookback,
        )
        channel_ids = list(bundle.channels_by_id.keys())
        latest = get_latest_snapshots_for_videos(session, list(bundle.records.keys()))

        for vid, rec in bundle.records.items():
            reason = radar_target_rejection_reason(
                content_format=rec.video.content_format,
                channel=rec.channel,
                latest_snapshot=rec.latest_snapshot,
            )
            if reason != REJECTION_UNKNOWN_SUBSCRIBERS:
                continue
            ch = rec.channel
            snap = rec.latest_snapshot
            resolved = resolve_known_subscribers(channel=ch, latest_snapshot=snap)
            if ch is None:
                cause = "no_channel_row"
            elif int(ch.subscribers_count or 0) > 0:
                cause = "positive_channel_should_not_happen"
            elif snap is None:
                cause = "channel_zero_no_snapshot"
            elif snap.subscribers is None:
                cause = "channel_zero_snapshot_subscribers_null"
            else:
                cause = "channel_zero_snapshot_subscribers_zero"
            causes[cause] += 1
            if len(examples) < 10:
                examples.append(
                    {
                        "video_id": vid,
                        "channel_id": rec.video.channel_id,
                        "cause": cause,
                        "channel_subscribers_count": ch.subscribers_count if ch else None,
                        "snapshot_subscribers": snap.subscribers if snap else None,
                        "resolved": resolved,
                        "content_format": rec.video.content_format.value,
                    },
                )

        print("unknown_subscribers_causes", dict(causes))
        print("examples")
        for row in examples:
            print(row)
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
