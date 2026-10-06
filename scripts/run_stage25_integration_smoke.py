#!/usr/bin/env python3
"""Stage 2.5 integration smoke on local restore DB only."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
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
ARTIFACT = ROOT / "artifacts" / "stage25_smoke_report.json"
ENRICHMENT_PASS_SEQUENCE = 1


def _local_database_url() -> str:
    load_dotenv(ROOT / ".env.docker")
    user = os.environ["RADAR_LOCAL_DB_USER"].strip()
    pw = quote(os.environ["RADAR_LOCAL_DB_PASSWORD"].strip(), safe="")
    return f"postgresql://{user}:{pw}@{EXPECTED_HOST}:{EXPECTED_PORT}/{EXPECTED_DB}"


def _assert_engine_url(engine) -> None:
    url = str(engine.url)
    parsed = urlparse(url)
    if parsed.hostname not in (EXPECTED_HOST, "localhost"):
        raise SystemExit(f"engine host mismatch: {parsed.hostname!r} url={url!r}")
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
            "daily_limit": ch_daily,
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
            "daily_limit": vid_daily,
        },
    }


def _planned_ids(session, *, pass_sequence: int = 1) -> dict:
    from app.services.radar_enrichment_config import radar_enrichment_settings
    from app.services.radar_enrichment_selection import (
        RadarEnrichmentPassContext,
        select_format_enrichment_video_ids,
        select_subscriber_enrichment_channel_ids,
    )
    from app.services.unknown_format_enrichment_config import unknown_format_enrichment_settings

    ctx = RadarEnrichmentPassContext(pass_sequence=pass_sequence)
    from app.services.radar_api_budget import (
        BUDGET_KIND_CHANNELS_LIST,
        BUDGET_KIND_VIDEOS_LIST,
        remaining_id_units,
    )

    now = datetime.now(timezone.utc)
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
        "channels": select_subscriber_enrichment_channel_ids(session, limit=ch_limit, context=ctx),
        "videos": select_format_enrichment_video_ids(session, limit=vid_limit, context=ctx),
    }


def _monitoring_admissible(session, video_ids: list[str]) -> dict:
    from sqlalchemy import select

    from app.models.orm import Channel, Video, VideoFormat
    from app.services.monitoring_radar_eligibility import monitoring_video_eligible
    from app.services.radar_target_eligibility import resolve_known_subscribers
    from app.services.video_format_api_verification import load_api_format_confirmed_video_ids
    from app.services.video_snapshot_storage import get_latest_snapshots_for_videos

    if not video_ids:
        return {"checked": 0, "violations": []}
    videos = {v.id: v for v in session.scalars(select(Video).where(Video.id.in_(video_ids))).all()}
    channel_ids = list({v.channel_id for v in videos.values() if v.channel_id})
    channels = {
        c.id: c for c in session.scalars(select(Channel).where(Channel.id.in_(channel_ids))).all()
    } if channel_ids else {}
    latest = get_latest_snapshots_for_videos(session, video_ids)
    confirmed = load_api_format_confirmed_video_ids(session, video_ids)
    violations = []
    for vid in video_ids:
        video = videos.get(vid)
        if video is None:
            violations.append({"video_id": vid, "reason": "missing_video"})
            continue
        ch = channels.get(video.channel_id)
        snap = latest.get(vid)
        subs = resolve_known_subscribers(channel=ch, latest_snapshot=snap)
        if not monitoring_video_eligible(
            video=video,
            channel=ch,
            latest_snapshot=snap,
            confirmed_regular_ids=confirmed,
        ):
            violations.append(
                {
                    "video_id": vid,
                    "format": video.content_format.value,
                    "subs": subs,
                    "confirmed": vid in confirmed,
                },
            )
    return {"checked": len(video_ids), "violations": violations}


def _snapshot_api(run_id: str | None) -> dict | None:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8001/api/attention/summary", timeout=8) as resp:
            payload = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"http_ok": False, "error": str(exc)}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else payload
    return {
        "http_ok": True,
        "api_run_id": summary.get("run_id"),
        "winner_count": summary.get("winner_count"),
        "pattern_count": summary.get("pattern_count"),
        "matches": summary.get("run_id") == run_id,
    }


def main() -> int:
    local_url = _local_database_url()
    load_dotenv(ROOT / ".env")
    os.environ["DATABASE_URL"] = local_url

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.api.deps import get_youtube_client
    from app.core.config import settings
    from app.db.migrations import run_startup_migrations
    from app.models.orm import VideoFormatEnrichmentAttempt
    from app.services.attention_read_model import refresh_attention_engine
    from app.services.attention_engine_types import AttentionEngineConfig
    from app.services.monitoring_cycle import run_monitoring_cycle
    from app.services.monitoring_tier_budget_policy import ApiBudgetPolicy
    from app.services.monitoring_video_source import load_monitored_video_states
    from app.services.radar_enrichment_orchestrator import run_radar_enrichment_pass
    from app.services.radar_enrichment_selection import RadarEnrichmentPassContext

    if not settings.youtube_api_keys:
        raise SystemExit("YOUTUBE_API_KEYS required for live enrichment/monitoring steps")

    report: dict = {"started_at": datetime.now(timezone.utc).isoformat(), "stages": {}}
    now = datetime.now(timezone.utc)

    engine = create_engine(local_url, pool_pre_ping=True)
    _assert_engine_url(engine)

    t0 = time.perf_counter()
    run_startup_migrations(engine)
    _assert_engine_url(engine)
    report["stages"]["migrations"] = {
        "seconds": round(time.perf_counter() - t0, 3),
        "engine_url": str(engine.url),
    }

    Session = sessionmaker(bind=engine)
    client = get_youtube_client()

    planned_before: dict = {"channels": [], "videos": []}

    # 2) dry-run
    session = Session()
    _assert_engine_url(session.get_bind())
    try:
        ledger_before = _ledger_snapshot(session, now)
        planned_before = _planned_ids(session, pass_sequence=ENRICHMENT_PASS_SEQUENCE)
        t1 = time.perf_counter()
        dry1 = run_radar_enrichment_pass(
            session,
            client,
            context=RadarEnrichmentPassContext(pass_sequence=ENRICHMENT_PASS_SEQUENCE),
            dry_run=True,
            now=now,
        )
        session.rollback()
        ledger_after_dry = _ledger_snapshot(session, now)
        report["stages"]["dry_run_1"] = {
            "seconds": round(time.perf_counter() - t1, 3),
            "planned_channels": planned_before["channels"],
            "planned_videos": planned_before["videos"],
            "ledger_before": ledger_before,
            "ledger_after": ledger_after_dry,
            "ledger_unchanged": ledger_before == ledger_after_dry,
            "pass_report": asdict(dry1),
        }
    finally:
        session.close()

    # 3) live pass
    session = Session()
    _assert_engine_url(session.get_bind())
    try:
        ledger_pre_live = _ledger_snapshot(session, now)
        monitored_before = len(load_monitored_video_states(session))
        planned_live = _planned_ids(session, pass_sequence=ENRICHMENT_PASS_SEQUENCE)
        t2 = time.perf_counter()
        live = run_radar_enrichment_pass(
            session,
            client,
            context=RadarEnrichmentPassContext(pass_sequence=ENRICHMENT_PASS_SEQUENCE),
            dry_run=False,
            now=now,
        )
        session.commit()
        ledger_post_live = _ledger_snapshot(session, now)
        live_processed_channels = planned_live["channels"][: live.subscriber_channels_processed]
        live_processed_videos = planned_live["videos"][: live.format_videos_processed]
        format_outcomes = {}
        if live_processed_videos:
            for row in session.scalars(
                select(VideoFormatEnrichmentAttempt).where(
                    VideoFormatEnrichmentAttempt.video_id.in_(live_processed_videos),
                ),
            ).all():
                format_outcomes[row.video_id] = row.last_outcome
        channel_statuses = {}
        if live_processed_channels:
            from app.models.orm import Channel

            for ch in session.scalars(
                select(Channel).where(Channel.id.in_(live_processed_channels)),
            ).all():
                channel_statuses[ch.id] = {
                    "subscribers_api_status": ch.subscribers_api_status,
                    "subscribers_count": int(ch.subscribers_count),
                }
        report["stages"]["live_enrichment"] = {
            "seconds": round(time.perf_counter() - t2, 3),
            "planned_channels": planned_live["channels"],
            "planned_videos": planned_live["videos"],
            "ledger_before": ledger_pre_live,
            "ledger_after": ledger_post_live,
            "pass_report": asdict(live),
            "format_outcomes": format_outcomes,
            "channel_statuses": channel_statuses,
            "monitored_states_before": monitored_before,
            "processed_channel_ids": live_processed_channels,
            "processed_video_ids": live_processed_videos,
        }
    finally:
        session.close()

    # 4) dry-run 2
    session = Session()
    _assert_engine_url(session.get_bind())
    try:
        planned_after = _planned_ids(session, pass_sequence=ENRICHMENT_PASS_SEQUENCE)
        overlap_ch = set(planned_after["channels"]) & set(
            report["stages"]["live_enrichment"].get("processed_channel_ids") or [],
        )
        overlap_vid = set(planned_after["videos"]) & set(
            report["stages"]["live_enrichment"].get("processed_video_ids") or [],
        )
        session.rollback()
        report["stages"]["dry_run_2"] = {
            "planned_channels": planned_after["channels"],
            "planned_videos": planned_after["videos"],
            "overlap_with_live_channels": sorted(overlap_ch),
            "overlap_with_live_videos": sorted(overlap_vid),
            "no_immediate_channel_repick": len(overlap_ch) == 0,
            "no_immediate_video_repick": len(overlap_vid) == 0,
        }
    finally:
        session.close()

    # 5) monitoring cycle cap 50 captures
    session = Session()
    _assert_engine_url(session.get_bind())
    try:
        monitored_pre = len(load_monitored_video_states(session))
        t3 = time.perf_counter()
        mon = run_monitoring_cycle(
            session,
            youtube_client=client,
            dry_run=False,
            budget_policy=ApiBudgetPolicy(max_capture_requests_per_cycle=50),
        )
        session.commit()
        monitored_post = len(load_monitored_video_states(session))
        from app.models.orm import VideoSnapshot

        capture_ids = list(
            dict.fromkeys(
                session.scalars(
                    select(VideoSnapshot.video_id).where(
                        VideoSnapshot.run_id.like(f"{mon.run_id}:%"),
                    ),
                ).all(),
            ),
        )
        admissible = _monitoring_admissible(session, capture_ids)
        report["stages"]["monitoring_cycle"] = {
            "seconds": round(time.perf_counter() - t3, 3),
            "summary": mon.__dict__,
            "monitored_states_before": monitored_pre,
            "monitored_states_after": monitored_post,
            "new_monitored_delta": monitored_post - monitored_pre,
            "capture_video_ids_checked": capture_ids[:50],
            "admissible_check": admissible,
        }
    finally:
        session.close()

    # 6) attention refresh
    session = Session()
    _assert_engine_url(session.get_bind())
    try:
        t4 = time.perf_counter()
        result = refresh_attention_engine(session, config=AttentionEngineConfig())
        session.commit()
        api = _snapshot_api(result.summary.run_id)
        report["stages"]["attention_refresh"] = {
            "seconds": round(time.perf_counter() - t4, 3),
            "run_id": result.summary.run_id,
            "winners": result.summary.winner_count,
            "patterns": result.summary.pattern_count,
            "families": len(result.families),
            "gating": result.summary.notes.get("published_winners_gating"),
            "snapshot_api": api,
        }
    finally:
        session.close()

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["total_seconds"] = round(
        sum(s.get("seconds", 0) for s in report["stages"].values() if isinstance(s, dict)),
        3,
    )

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
