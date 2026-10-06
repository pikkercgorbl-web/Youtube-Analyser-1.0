#!/usr/bin/env python3
"""Stage 2.4: verify 19 winner formats, ordinary refresh, publish gating report."""

from __future__ import annotations

import json
import logging
import os
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

EXPECTED_HOST = "127.0.0.1"
EXPECTED_PORT = 5433
EXPECTED_DB = "youtube_radar_restore_check"
ARTIFACT = ROOT / "artifacts" / "stage24_report.json"


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


def _participant_format_audit(
    session,
    video_ids: set[str],
    confirmed: frozenset[str],
) -> dict[str, int]:
    from sqlalchemy import select

    from app.models.orm import Video, VideoFormat

    rows = session.scalars(select(Video).where(Video.id.in_(list(video_ids)))).all() if video_ids else []
    unverified = 0
    confirmed_n = 0
    other = 0
    for row in rows:
        if row.content_format not in (VideoFormat.MEDIUM, VideoFormat.LONG):
            other += 1
            continue
        if row.id in confirmed:
            confirmed_n += 1
        else:
            unverified += 1
    return {
        "participants_total": len(video_ids),
        "medium_long_confirmed": confirmed_n,
        "medium_long_unverified": unverified,
        "non_medium_long": other,
    }


def _subscriber_source_audit(bundle) -> dict[str, int]:
    from app.services.radar_target_eligibility import resolve_subscriber_provenance

    sources: Counter[str] = Counter()
    unknown = 0
    for rec in bundle.records.values():
        count, source = resolve_subscriber_provenance(
            channel=rec.channel,
            latest_snapshot=rec.latest_snapshot,
        )
        if count is None:
            unknown += 1
        elif source:
            sources[source] += 1
    return {
        "known_channel_api": int(sources["channel_api"]),
        "known_snapshot": int(sources["snapshot"]),
        "unknown": unknown,
    }


def _try_snapshot_api(run_id: str | None) -> dict | None:
    import urllib.error
    import urllib.request

    url = "http://127.0.0.1:8001/api/attention/summary"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = json.loads(resp.read().decode())
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else payload
        api_run_id = summary.get("run_id")
        return {
            "http_ok": True,
            "api_run_id": api_run_id,
            "api_winner_count": summary.get("winner_count"),
            "api_data_source": summary.get("source"),
            "matches_persisted_run_id": api_run_id == run_id,
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"http_ok": False, "error": str(exc)}


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    local_url = _local_database_url()
    load_dotenv(ROOT / ".env")
    os.environ["DATABASE_URL"] = local_url

    from datetime import timedelta

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.config import settings
    from app.db.migrations import run_startup_migrations
    from app.integrations.youtube.client import YouTubeApiClient
    from app.integrations.youtube.key_manager import YouTubeApiKeyManager
    from app.services.attention_engine_service import compute_attention_engine
    from app.services.attention_engine_types import AttentionEngineConfig
    from app.services.attention_evidence import load_attention_evidence
    from app.services.attention_read_model import get_latest_attention_run, refresh_attention_engine
    from app.services.channel_subscriber_backfill import select_unknown_subscriber_channel_ids
    from app.services.historical_video_format_verification import (
        OUTCOME_CONFIRMED_REGULAR,
        verify_video_id_batches,
    )
    from app.services.radar_target_eligibility import summarize_video_eligibility
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

        raw_compute = compute_attention_engine(
            session,
            config=AttentionEngineConfig(),
            source="stage24_compute_unfiltered",
        )
        ws, we = raw_compute.summary.window_start, raw_compute.summary.window_end
        bundle = load_attention_evidence(
            session,
            window_start=ws,
            window_end=we,
            channel_lookback_start=we - timedelta(days=14),
        )
        eligibility = summarize_video_eligibility(
            [(r.video, r.channel, r.latest_snapshot) for r in bundle.records.values()],
        )
        confirmed_before = load_api_format_confirmed_video_ids(session)
        unverified_ids = [
            w.video_id
            for w in raw_compute.video_winners
            if w.video_id not in confirmed_before
        ][:19]

        format_report = verify_video_id_batches(session, client, unverified_ids, record_attempts=True)
        session.commit()

        confirmed_after = load_api_format_confirmed_video_ids(session)

        refresh = refresh_attention_engine(session, config=AttentionEngineConfig())
        session.commit()

        latest = get_latest_attention_run(session)
        gating = refresh.summary.notes.get("published_winners_gating", {})
        pattern_vids: set[str] = set()
        for p in refresh.patterns:
            pattern_vids.update(p.participating_video_ids)
        family_vids: set[str] = set()
        for f in refresh.families:
            family_vids.update(f.video_ids)

        from app.services.radar_target_eligibility import (
            REJECTION_UNKNOWN_SUBSCRIBERS,
            radar_target_rejection_reason,
        )

        unknown_channel_ids_in_window: set[str] = set()
        for rec in bundle.records.values():
            if (
                radar_target_rejection_reason(
                    content_format=rec.video.content_format,
                    channel=rec.channel,
                    latest_snapshot=rec.latest_snapshot,
                )
                == REJECTION_UNKNOWN_SUBSCRIBERS
            ):
                if rec.video.channel_id:
                    unknown_channel_ids_in_window.add(rec.video.channel_id)

        backfill_queue_sample = select_unknown_subscriber_channel_ids(
            session,
            limit=500,
            window_start=ws,
            window_end=we,
        )

        report = {
            "eligibility_current_policy": eligibility.to_dict(),
            "subscriber_sources_in_window": _subscriber_source_audit(bundle),
            "compute_unfiltered": {
                "winner_count_capped_at_50": len(raw_compute.video_winners),
                "unverified_in_top50": len(
                    [w for w in raw_compute.video_winners if w.video_id not in confirmed_before],
                ),
            },
            "format_verification_batch": {
                "requested": len(unverified_ids),
                "video_ids": unverified_ids,
                "api_batches": format_report.api_batch_count,
                "confirmed_regular": format_report.confirmed_regular,
                "live_or_broadcast": format_report.live_or_broadcast,
                "missing": format_report.missing,
                "unresolved": format_report.unresolved,
                "outcomes_by_video_id": format_report.outcomes_by_video_id,
            },
            "published_refresh": {
                "run_id": latest.run_id if latest else refresh.summary.run_id,
                "published_winners_gating": gating,
                "published_winner_count": refresh.summary.winner_count,
                "pattern_count": refresh.summary.pattern_count,
                "family_count": len(refresh.families),
            },
            "patterns_participants": _participant_format_audit(session, pattern_vids, confirmed_after),
            "families_participants": _participant_format_audit(session, family_vids, confirmed_after),
            "channels_without_known_subscribers": {
                "unique_in_attention_window": len(unknown_channel_ids_in_window),
                "backfill_queue_next_500": len(backfill_queue_sample),
            },
            "snapshot_api": _try_snapshot_api(latest.run_id if latest else None),
        }

        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps(report, indent=2, default=str))
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
