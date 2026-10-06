#!/usr/bin/env python3
"""Enrichment closure audit — DB only, no YouTube HTTP."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
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
ARTIFACT = ROOT / "artifacts" / "stage25_enrichment_closure_audit.json"
VERIFY = ROOT / "artifacts" / "stage25_enrichment_verify.json"


def _db_url() -> str:
    load_dotenv(ROOT / ".env.docker")
    user = os.environ["RADAR_LOCAL_DB_USER"].strip()
    pw = quote(os.environ["RADAR_LOCAL_DB_PASSWORD"].strip(), safe="")
    return f"postgresql://{user}:{pw}@{EXPECTED_HOST}:{EXPECTED_PORT}/{EXPECTED_DB}"


def _assert_engine(engine) -> None:
    parsed = urlparse(str(engine.url))
    if parsed.hostname not in (EXPECTED_HOST, "localhost"):
        raise SystemExit(f"host mismatch: {parsed.hostname!r}")
    if parsed.port not in (EXPECTED_PORT, None):
        raise SystemExit(f"port mismatch: {parsed.port!r}")
    db = (parsed.path or "").lstrip("/")
    if db != EXPECTED_DB:
        raise SystemExit(f"db mismatch: {db!r}")


def _load_format_batch(session):
    from sqlalchemy import func, select

    from app.models.orm import VideoFormatEnrichmentAttempt
    from app.services.video_format_outcomes import OUTCOME_CONFIRMED_REGULAR, OUTCOME_LIVE, OUTCOME_MISSING

    day_start = datetime(2026, 10, 6, 11, 0, tzinfo=timezone.utc)
    day_end = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    rows = session.scalars(
        select(VideoFormatEnrichmentAttempt)
        .where(
            VideoFormatEnrichmentAttempt.last_attempt_at >= day_start,
            VideoFormatEnrichmentAttempt.last_attempt_at < day_end,
        )
        .order_by(VideoFormatEnrichmentAttempt.last_attempt_at.desc()),
    ).all()
    if not rows:
        return [], {}
    stamp = rows[0].last_attempt_at
    batch = [r for r in rows if r.last_attempt_at == stamp]
    if len(batch) < 50:
        by_time = session.execute(
            select(
                VideoFormatEnrichmentAttempt.last_attempt_at,
                func.count(),
            )
            .where(
                VideoFormatEnrichmentAttempt.last_attempt_at >= day_start,
                VideoFormatEnrichmentAttempt.last_attempt_at < day_end,
            )
            .group_by(VideoFormatEnrichmentAttempt.last_attempt_at)
            .order_by(func.count().desc())
        ).all()
        if by_time:
            stamp = by_time[0][0]
            batch = session.scalars(
                select(VideoFormatEnrichmentAttempt).where(
                    VideoFormatEnrichmentAttempt.last_attempt_at == stamp,
                ),
            ).all()
    outcomes = {r.video_id: r.last_outcome for r in batch}
    groups = Counter(outcomes.values())
    return list(outcomes.keys()), {
        "attempt_at": stamp.isoformat() if stamp else None,
        "count": len(batch),
        "outcomes": dict(groups),
        OUTCOME_CONFIRMED_REGULAR: [
            vid for vid, o in outcomes.items() if o == OUTCOME_CONFIRMED_REGULAR
        ],
        OUTCOME_LIVE: [vid for vid, o in outcomes.items() if o == OUTCOME_LIVE],
        OUTCOME_MISSING: [vid for vid, o in outcomes.items() if o == OUTCOME_MISSING],
    }


def _pass_context_from_verify() -> tuple[set[str], set[str], int, datetime | None]:
    if not VERIFY.is_file():
        return set(), set(), 1, None
    data = json.loads(VERIFY.read_text(encoding="utf-8"))
    live = data.get("live_pass", {}).get("pass_report", {}).get("notes", {})
    touched = set(live.get("subscriber_batches", [{}])[0].get("channel_ids") or [])
    eligible = set(live.get("subscriber_touched_eligible_for_format") or [])
    seq = int(live.get("pass_sequence") or 1)
    started = data.get("started_at")
    now = datetime.fromisoformat(started) if started else None
    return touched, eligible, seq, now


def _format_video_audit(session, video_ids: list[str], touched: set[str], eligible: set[str], now: datetime):
    from sqlalchemy import select

    from app.models.orm import Channel, KeywordDiscoveryHit, Video
    from app.services.radar_enrichment_selection import (
        RadarEnrichmentPassContext,
        diagnose_format_enrichment_selection,
    )
    from app.services.radar_target_eligibility import (
        RADAR_MAX_CHANNEL_SUBSCRIBERS,
        radar_target_rejection_reason,
        resolve_known_subscribers,
    )
    from app.services.video_format_batch_apply import video_needs_format_enrichment
    from app.services.video_format_api_verification import load_api_format_confirmed_video_ids

    ctx = RadarEnrichmentPassContext(pass_sequence=1)
    diag_touched = diagnose_format_enrichment_selection(
        session,
        channel_ids=touched,
        context=ctx,
        now=now,
    )
    diag_eligible = diagnose_format_enrichment_selection(
        session,
        channel_ids=eligible,
        context=ctx,
        now=now,
    ) if eligible else {}

    recent_cutoff = now - __import__("datetime").timedelta(hours=48)
    recent_hits = set(
        session.scalars(
            select(KeywordDiscoveryHit.video_id).where(
                KeywordDiscoveryHit.discovered_at >= recent_cutoff,
            ),
        ).all(),
    )

    videos = {v.id: v for v in session.scalars(select(Video).where(Video.id.in_(video_ids))).all()}
    channel_ids = list({v.channel_id for v in videos.values() if v.channel_id})
    channels = {
        c.id: c
        for c in session.scalars(select(Channel).where(Channel.id.in_(channel_ids))).all()
    }
    confirmed = load_api_format_confirmed_video_ids(session, video_ids)

    per_video = []
    for vid in video_ids:
        video = videos.get(vid)
        ch = channels.get(video.channel_id) if video and video.channel_id else None
        subs = resolve_known_subscribers(channel=ch, latest_snapshot=None)
        rej = (
            radar_target_rejection_reason(
                content_format=video.content_format,
                channel=ch,
                latest_snapshot=None,
            )
            if video
            else "missing_video"
        )
        pool = []
        if video and video.channel_id in touched:
            pool.append("subscriber_touched_batch")
        if video and video.channel_id in eligible:
            pool.append("eligible_known_subs_le100k")
        if vid in recent_hits:
            pool.append("recent_discovery_hit")
        if video and video.channel_id in touched and video.channel_id not in eligible:
            pool.append("touched_but_channel_over_sub_cap")
        if video and video.channel_id not in touched and video.channel_id in eligible:
            pool.append("eligible_backlog_not_in_subscriber_batch")
        if not pool:
            pool.append("other_backlog")
        per_video.append(
            {
                "video_id": vid,
                "channel_id": video.channel_id if video else None,
                "subscribers": subs,
                "subscribers_ok_at_selection": subs is not None and subs <= RADAR_MAX_CHANNEL_SUBSCRIBERS,
                "radar_rejection": rej,
                "in_recent_hit": vid in recent_hits,
                "pool_source": pool,
            },
        )

    subs_fail_selected = [r for r in per_video if not r["subscribers_ok_at_selection"]]
    not_in_eligible = [r for r in per_video if r["channel_id"] and r["channel_id"] not in eligible]

    return {
        "diagnose_on_subscriber_touched_channels": diag_touched,
        "diagnose_on_eligible_channels_only": diag_eligible,
        "format_batch_videos": len(video_ids),
        "subscriber_ok_among_selected": sum(1 for r in per_video if r["subscribers_ok_at_selection"]),
        "subs_fail_among_selected": subs_fail_selected,
        "selected_not_in_eligible_channel_set": not_in_eligible,
        "pool_source_counts": dict(Counter(p for r in per_video for p in r["pool_source"])),
        "per_video": per_video,
    }


def _monitoring_audit(session, batch_meta: dict):
    from sqlalchemy import select

    from app.models.orm import Channel, Video
    from app.services.monitoring_radar_eligibility import monitoring_video_eligible
    from app.services.monitoring_video_source import load_monitored_video_states
    from app.services.radar_target_eligibility import radar_target_rejection_reason
    from app.services.video_format_api_verification import load_api_format_confirmed_video_ids
    from app.services.video_snapshot_storage import get_latest_snapshots_for_videos

    monitored_ids = {s.video_id for s in load_monitored_video_states(session)}
    from app.services.video_format_outcomes import OUTCOME_CONFIRMED_REGULAR, OUTCOME_LIVE, OUTCOME_MISSING

    confirmed_ids = batch_meta.get(OUTCOME_CONFIRMED_REGULAR) or []
    live_ids = batch_meta.get(OUTCOME_LIVE) or []
    missing_ids = batch_meta.get(OUTCOME_MISSING) or []

    def _check_group(label: str, video_ids: list[str]) -> dict:
        if not video_ids:
            return {"label": label, "count": 0}
        videos = {v.id: v for v in session.scalars(select(Video).where(Video.id.in_(video_ids))).all()}
        channel_ids = list({v.channel_id for v in videos.values() if v.channel_id})
        channels = {
            c.id: c
            for c in session.scalars(select(Channel).where(Channel.id.in_(channel_ids))).all()
        }
        latest = get_latest_snapshots_for_videos(session, video_ids)
        confirmed = load_api_format_confirmed_video_ids(session, video_ids)
        admitted = []
        excluded = []
        for vid in video_ids:
            video = videos.get(vid)
            if video is None:
                excluded.append({"video_id": vid, "reason": "missing_video"})
                continue
            ch = channels.get(video.channel_id)
            snap = latest.get(vid)
            if monitoring_video_eligible(
                video=video,
                channel=ch,
                latest_snapshot=snap,
                confirmed_regular_ids=confirmed,
            ):
                admitted.append(vid)
            else:
                rej = radar_target_rejection_reason(
                    content_format=video.content_format,
                    channel=ch,
                    latest_snapshot=snap,
                )
                excluded.append(
                    {
                        "video_id": vid,
                        "content_format": video.content_format.value,
                        "radar_rejection": rej,
                        "confirmed_regular": vid in confirmed,
                        "in_monitored_pool": vid in monitored_ids,
                    },
                )
        return {
            "label": label,
            "count": len(video_ids),
            "admitted": len(admitted),
            "excluded": excluded,
            "in_working_monitoring_selection": sorted(set(video_ids) & monitored_ids),
        }

    return {
        "confirmed_regular": _check_group("confirmed_regular", confirmed_ids),
        "live_or_broadcast": _check_group("live_or_broadcast", live_ids),
        "missing": _check_group("missing", missing_ids),
        "monitored_pool_total": len(monitored_ids),
    }


def _enrichment_dry_run_pass(session, now: datetime):
    from app.services.radar_enrichment_orchestrator import run_radar_enrichment_pass
    from app.services.radar_enrichment_selection import RadarEnrichmentPassContext

    class _DryRunClient:
        def get_channels(self, channel_ids: list[str]):
            return {}

        def get_videos(self, video_ids: list[str]):
            return []

    report = run_radar_enrichment_pass(
        session,
        _DryRunClient(),
        context=RadarEnrichmentPassContext(pass_sequence=1),
        dry_run=True,
        now=now,
    )
    session.rollback()
    return {
        "subscriber_channels_planned": report.subscriber_channels_planned,
        "subscriber_channel_ids_dry_run": report.subscriber_channels_processed,
        "subscriber_http_batches_dry_run": report.subscriber_http_batches,
        "format_videos_planned": report.format_videos_planned,
        "format_video_ids_dry_run": report.format_videos_processed,
        "format_http_batches_dry_run": report.format_http_batches,
        "errors": list(report.errors),
        "note": (
            "Dry-run: no ledger reservation, no HTTP. "
            "http_batches_* is the batch count that would run (50 IDs per batch)."
        ),
    }


def _enrichment_pending_queue(session, now: datetime) -> dict:
    from sqlalchemy import func, select

    from app.models.orm import Channel, Video, VideoFormatEnrichmentAttempt
    from app.services.radar_enrichment_selection import (
        RadarEnrichmentPassContext,
        select_format_enrichment_video_ids,
        select_subscriber_enrichment_channel_ids,
    )

    cap = 10_000
    ctx = RadarEnrichmentPassContext(pass_sequence=1)
    channel_ids = select_subscriber_enrichment_channel_ids(
        session,
        limit=cap,
        context=ctx,
        now=now,
    )
    video_ids = select_format_enrichment_video_ids(
        session,
        limit=cap,
        context=ctx,
        now=now,
    )
    oldest_channel_updated_at = None
    if channel_ids:
        oldest_channel_updated_at = session.scalar(
            select(func.min(Channel.updated_at)).where(Channel.id.in_(channel_ids[:5000])),
        )
    oldest_video_updated_at = None
    oldest_format_attempt_at = None
    if video_ids:
        sample = video_ids[:5000]
        oldest_video_updated_at = session.scalar(
            select(func.min(Video.updated_at)).where(Video.id.in_(sample)),
        )
        oldest_format_attempt_at = session.scalar(
            select(func.min(VideoFormatEnrichmentAttempt.last_attempt_at)).where(
                VideoFormatEnrichmentAttempt.video_id.in_(sample),
            ),
        )
    return {
        "subscriber_channels_due": len(channel_ids),
        "format_videos_due": len(video_ids),
        "count_cap": cap,
        "at_least_cap_hit": {
            "subscriber": len(channel_ids) >= cap,
            "format": len(video_ids) >= cap,
        },
        "oldest_among_due_sample": {
            "subscriber_channel_updated_at": (
                oldest_channel_updated_at.isoformat() if oldest_channel_updated_at else None
            ),
            "format_video_updated_at": (
                oldest_video_updated_at.isoformat() if oldest_video_updated_at else None
            ),
            "format_last_attempt_at": (
                oldest_format_attempt_at.isoformat() if oldest_format_attempt_at else None
            ),
            "sample_size": 5000,
        },
        "note": "Due counts use same selection rules as a live pass (dedup, cooldown, backoff).",
    }


def _monitoring_outcome_http_accounting(session, now: datetime) -> dict:
    from sqlalchemy import func, select

    from app.models.orm import MonitoringCycleRun, OutcomeCaptureCycleRun
    from app.services.radar_api_budget import utc_calendar_day

    day = utc_calendar_day(now)
    day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    mon_row = session.execute(
        select(
            func.count(MonitoringCycleRun.id),
            func.coalesce(func.sum(MonitoringCycleRun.selected_request_count), 0),
            func.coalesce(func.sum(MonitoringCycleRun.fetch_failed_count), 0),
        ).where(MonitoringCycleRun.started_at >= day_start),
    ).one()
    out_row = session.execute(
        select(
            func.count(OutcomeCaptureCycleRun.id),
            func.coalesce(func.sum(OutcomeCaptureCycleRun.selected_video_count), 0),
            func.coalesce(func.sum(OutcomeCaptureCycleRun.fetch_failed_count), 0),
        ).where(OutcomeCaptureCycleRun.started_at >= day_start),
    ).one()
    return {
        "monitoring": {
            "accounting_available": True,
            "metric": "sum(selected_request_count) on monitoring_cycle_runs for UTC day",
            "not_raw_http_counter": True,
            "cycles_started": int(mon_row[0]),
            "selected_request_count_sum": int(mon_row[1]),
            "fetch_failed_count_sum": int(mon_row[2]),
        },
        "outcome_capture": {
            "accounting_available": True,
            "metric": "sum(selected_video_count) on outcome_capture_cycle_runs for UTC day",
            "not_raw_http_counter": True,
            "cycles_started": int(out_row[0]),
            "selected_video_count_sum": int(out_row[1]),
            "fetch_failed_count_sum": int(out_row[2]),
        },
    }


def _quota_and_rate_limit_errors() -> dict:
    verify_errors: list[str] = []
    if VERIFY.is_file():
        data = json.loads(VERIFY.read_text(encoding="utf-8"))
        live = data.get("live_pass", {}).get("pass_report", {})
        verify_errors = list(live.get("errors") or [])
    return {
        "persisted_db_accounting": False,
        "verify_json_live_pass_errors": verify_errors or None,
        "note": (
            "No dedicated quota/rate-limit error table. "
            "YouTube client tries each configured API key once per HTTP call, then raises YouTubeApiError."
        ),
    }


def _youtube_key_rotation_policy() -> dict:
    keys_raw = os.environ.get("YOUTUBE_API_KEYS", "")
    key_count = len([k for k in keys_raw.split(",") if k.strip()]) if keys_raw.strip() else None
    return {
        "max_rotations_per_request": key_count,
        "infinite_rotation": False,
        "configured_key_count": key_count,
    }


def _attention_refresh(session):
    from app.services.attention_engine_types import AttentionEngineConfig
    from app.services.attention_read_model import refresh_attention_engine

    result = refresh_attention_engine(session, config=AttentionEngineConfig())
    session.commit()
    summary = result.summary
    return {
        "run_id": summary.run_id,
        "winners": summary.winner_count,
        "patterns": summary.pattern_count,
        "families": len(result.families),
        "notes": summary.notes,
    }


def _snapshot_api(run_id: str | None) -> dict:
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
        "matches_refresh_run_id": summary.get("run_id") == run_id,
    }


def main() -> int:
    url = _db_url()
    os.environ["DATABASE_URL"] = url
    load_dotenv(ROOT / ".env")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(url, pool_pre_ping=True)
    _assert_engine(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    _assert_engine(session.get_bind())

    report: dict = {"generated_at": datetime.now(timezone.utc).isoformat()}
    now_utc = datetime.now(timezone.utc)

    from app.services.radar_api_budget import enrichment_daily_budget_summary

    ledger = enrichment_daily_budget_summary(session, now=now_utc)
    report["enrichment_limits_and_ledger"] = ledger
    report["enrichment_usage_today"] = {
        "channels_list": {
            "id_units_processed_reserved": ledger["channels_list"]["id_units_reserved"],
            "http_attempts_recorded": ledger["channels_list"]["http_requests"],
        },
        "videos_list": {
            "id_units_processed_reserved": ledger["videos_list"]["id_units_reserved"],
            "http_attempts_recorded": ledger["videos_list"]["http_requests"],
        },
        "note": "Reserved ID units come from radar_api_budget_daily (ledger not reset when limits change).",
    }
    report["enrichment_dry_run_pass"] = _enrichment_dry_run_pass(session, now_utc)
    report["enrichment_pending_queue"] = _enrichment_pending_queue(session, now_utc)
    report["monitoring_outcome_http_accounting"] = _monitoring_outcome_http_accounting(session, now_utc)
    report["quota_and_rate_limit_errors"] = _quota_and_rate_limit_errors()
    report["youtube_api_key_rotation"] = _youtube_key_rotation_policy()

    video_ids, batch_meta = _load_format_batch(session)
    report["format_batch"] = batch_meta
    touched, eligible, pass_seq, pass_now = _pass_context_from_verify()
    if pass_now is None:
        pass_now = datetime.now(timezone.utc)

    verify_live = json.loads(VERIFY.read_text(encoding="utf-8")).get("live_pass", {}).get("pass_report", {})
    report["verify_pass_counts"] = {
        "format_confirmed_regular": verify_live.get("format_confirmed_regular"),
        "format_live_or_broadcast": verify_live.get("format_live_or_broadcast"),
        "format_missing": verify_live.get("format_missing"),
        "format_selection_after_subscribers": (verify_live.get("notes") or {}).get(
            "format_selection_after_subscribers",
        ),
    }
    report["explanation_49_vs_50"] = (
        "diagnose_format_enrichment_selection — sample на subscriber_touched_channel_ids. "
        "format selection: priority на touched каналах, затем глобальный backlog; "
        "eligible SQL/keyset до LIMIT (без limit×30)."
    )

    if video_ids:
        report["format_video_audit"] = _format_video_audit(
            session,
            video_ids,
            touched,
            eligible,
            pass_now,
        )

    report["monitoring"] = _monitoring_audit(session, batch_meta)
    if os.environ.get("STAGE25_SKIP_ATTENTION", "").strip().lower() in ("1", "true", "yes"):
        report["attention"] = {"skipped": True, "reason": "STAGE25_SKIP_ATTENTION set"}
        report["snapshot_api"] = _snapshot_api(None)
    else:
        report["attention"] = _attention_refresh(session)
        report["snapshot_api"] = _snapshot_api(report["attention"]["run_id"])

    session.close()
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
