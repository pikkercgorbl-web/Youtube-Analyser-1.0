#!/usr/bin/env python3
"""Read-only Radar inactivity audit (no writes, no YouTube, no refresh)."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WINDOW_HOURS = 9


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _database_url_for_audit() -> str | None:
    """Prefer .env file (production laptop) over stale shell env (e.g. sqlite default)."""
    env_path = ROOT / ".env"
    if env_path.is_file():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("DATABASE_URL") or None


def _parse_db_url() -> dict:
    raw = _database_url_for_audit() or ""
    if not raw:
        return {"configured": False}
    p = urlparse(raw.replace("postgres://", "postgresql://"))
    return {
        "configured": True,
        "host": p.hostname,
        "port": p.port,
        "database": (p.path or "").lstrip("/") or None,
    }


def _process_scan() -> list[dict]:
    out: list[dict] = []
    pat = re.compile(
        r"discovery|monitoring|outcome|attention|keyword|run_.*worker|refresh_attention|"
        r"backfill_keyword|start-",
        re.I,
    )
    try:
        import psutil
    except ImportError:
        return [{"error": "psutil not installed; process list skipped"}]

    for proc in psutil.process_iter(["pid", "name", "create_time", "cmdline", "status"]):
        try:
            info = proc.info
            cmd = " ".join(info.get("cmdline") or [])
            name = (info.get("name") or "").lower()
            if not pat.search(cmd):
                continue
            if "python" not in name and "powershell" not in name:
                continue
            ct = info.get("create_time")
            start_utc = (
                datetime.fromtimestamp(ct, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if ct
                else None
            )
            out.append(
                {
                    "pid": info.get("pid"),
                    "name": info.get("name"),
                    "status": info.get("status"),
                    "start_utc": start_utc,
                    "cmdline": cmd[:400],
                },
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sorted(out, key=lambda x: (x.get("name") or "", x.get("pid") or 0))


def _read_log_tail(pattern: str, max_lines: int = 30) -> list[str]:
    lines: list[str] = []
    for base in (ROOT / "logs", ROOT / "logs" / "scheduled"):
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
            if not path.is_file():
                continue
            if pattern.lower() not in path.name.lower() and pattern.lower() not in str(path).lower():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace").splitlines()
                tail = text[-max_lines:]
                lines.extend([f"{path.name}: {ln}" for ln in tail if ln.strip()])
            except OSError:
                pass
            if len(lines) >= max_lines:
                break
    return lines[:max_lines]


def main() -> int:
    from migrate import load_dotenv

    load_dotenv(ROOT / ".env")
    now = _utc_now()
    window_start = now - timedelta(hours=WINDOW_HOURS)

    report: dict = {
        "audit_at_utc": _fmt(now),
        "audit_at_local": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z"),
        "window_hours": WINDOW_HOURS,
        "window_start_utc": _fmt(window_start),
        "database": _parse_db_url(),
        "processes": _process_scan(),
    }

    db = _parse_db_url()
    if not db.get("configured"):
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    db_url = _database_url_for_audit()
    assert db_url
    engine = create_engine(db_url.replace("postgres://", "postgresql://"))
    engine.echo = False
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()

    try:
        # Worker state tables
        disc = session.execute(
            text(
                """
                SELECT status, lock_holder, lock_acquired_at,
                       last_cycle_started_at, last_cycle_finished_at, last_run_id,
                       last_cycle_status, last_error
                FROM discovery_worker_state WHERE id = 1
                """
            ),
        ).mappings().first()
        mon = session.execute(
            text(
                """
                SELECT status, lock_holder, lock_acquired_at, updated_at
                FROM monitoring_worker_state WHERE id = 1
                """
            ),
        ).mappings().first()
        worker_rows = []
        if disc:
            worker_rows.append({"worker": "discovery", **dict(disc)})
        if mon:
            worker_rows.append({"worker": "monitoring", **dict(mon)})

        stale_discovery_min = 90
        stale_monitoring_min = 90
        workers: list[dict] = []
        for row in worker_rows:
            lock_at = row.get("lock_acquired_at")
            stale = False
            if lock_at is not None:
                la = lock_at if lock_at.tzinfo else lock_at.replace(tzinfo=timezone.utc)
                stale = (now - la).total_seconds() > stale_discovery_min * 60
            workers.append(
                {
                    "worker": row["worker"],
                    "status": row["status"],
                    "lock_holder": row["lock_holder"],
                    "lock_acquired_at_utc": _fmt(lock_at),
                    "lock_stale_90m": stale,
                    "last_cycle_started_utc": _fmt(row.get("last_cycle_started_at")),
                    "last_cycle_finished_utc": _fmt(row.get("last_cycle_finished_at")),
                    "last_run_id": row.get("last_run_id"),
                    "last_cycle_status": row.get("last_cycle_status"),
                    "last_error": (row.get("last_error") or "")[:500] or None,
                },
            )
        report["worker_state"] = workers

        # Recent cycle runs from tables if exist
        cycle_runs: dict = {}
        for table, col in (
            ("discovery_worker_state", None),
            ("monitoring_cycle_runs", "started_at"),
        ):
            insp = session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_name=:t)"
                ),
                {"t": table},
            ).scalar()
            if not insp:
                continue
        if session.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='monitoring_cycle_runs')"
            ),
        ).scalar():
            mr = session.execute(
                text(
                    """
                    SELECT run_id, started_at, finished_at, cycle_status,
                           loaded_video_count, selected_request_count, inserted_snapshot_count,
                           fetch_failed_count, runtime_seconds
                    FROM monitoring_cycle_runs
                    ORDER BY started_at DESC NULLS LAST
                    LIMIT 5
                    """
                ),
            ).mappings().all()
            cycle_runs["monitoring_last_5"] = [
                {k: (_fmt(v) if isinstance(v, datetime) else v) for k, v in dict(r).items()} for r in mr
            ]

        if session.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='keyword_scan_runs')"
            ),
        ).scalar():
            dr = session.execute(
                text(
                    """
                    SELECT discovery_run_id, MIN(started_at) AS started,
                           MAX(finished_at) AS finished,
                           COUNT(*) AS keywords,
                           SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok_n,
                           SUM(persisted_videos) AS persisted
                    FROM keyword_scan_runs
                    WHERE started_at >= :since
                    GROUP BY discovery_run_id
                    ORDER BY MIN(started_at) DESC
                    LIMIT 8
                    """
                ),
                {"since": window_start},
            ).mappings().all()
            cycle_runs["discovery_runs_in_window"] = [
                {k: (_fmt(v) if isinstance(v, datetime) else v) for k, v in dict(r).items()} for r in dr
            ]
            last_disc = session.execute(
                text(
                    """
                    SELECT discovery_run_id, MIN(started_at) AS started,
                           MAX(finished_at) AS finished,
                           COUNT(*) AS keywords,
                           SUM(persisted_videos) AS persisted
                    FROM keyword_scan_runs
                    GROUP BY discovery_run_id
                    ORDER BY MIN(started_at) DESC
                    LIMIT 1
                    """
                ),
            ).mappings().first()
            cycle_runs["discovery_last_run"] = (
                {k: (_fmt(v) if isinstance(v, datetime) else v) for k, v in dict(last_disc).items()}
                if last_disc
                else None
            )

        report["cycle_runs"] = cycle_runs

        # VideoSnapshot 9h by source
        snap = session.execute(
            text(
                """
                SELECT source, COUNT(*) AS n,
                       MIN(captured_at) AS first_at, MAX(captured_at) AS last_at
                FROM video_snapshots
                WHERE captured_at >= :since
                GROUP BY source
                ORDER BY n DESC
                """
            ),
            {"since": window_start},
        ).mappings().all()
        report["snapshots_9h_by_source"] = [
            {
                "source": r["source"],
                "count": int(r["n"]),
                "first_utc": _fmt(r["first_at"]),
                "last_utc": _fmt(r["last_at"]),
            }
            for r in snap
        ]
        report["snapshots_9h_total"] = sum(int(r["n"]) for r in snap)

        # Discovery hits / new videos in window
        hits = session.execute(
            text(
                """
                SELECT COUNT(*) AS hits,
                       COUNT(DISTINCT video_id) AS distinct_videos,
                       MAX(discovered_at) AS last_hit
                FROM keyword_discovery_hits
                WHERE discovered_at >= :since
                """
            ),
            {"since": window_start},
        ).mappings().first()
        report["discovery_hits_9h"] = {
            "hits": int(hits["hits"] or 0),
            "distinct_videos": int(hits["distinct_videos"] or 0),
            "last_hit_utc": _fmt(hits["last_hit"]),
        }

        vids = session.execute(
            text(
                """
                SELECT COUNT(*) AS n, MAX(updated_at) AS last_up
                FROM videos
                WHERE updated_at >= :since
                """
            ),
            {"since": window_start},
        ).mappings().first()
        report["videos_updated_9h"] = {
            "count": int(vids["n"] or 0),
            "last_updated_utc": _fmt(vids["last_up"]),
        }

        # Enrichment attempts in window
        sub_att = session.execute(
            text(
                """
                SELECT COUNT(*) AS n, MAX(last_attempt_at) AS last_at
                FROM channel_subscriber_enrichment_attempts
                WHERE last_attempt_at >= :since
                """
            ),
            {"since": window_start},
        ).mappings().first()
        fmt_att = session.execute(
            text(
                """
                SELECT COUNT(*) AS n, MAX(last_attempt_at) AS last_at
                FROM video_format_enrichment_attempts
                WHERE last_attempt_at >= :since
                """
            ),
            {"since": window_start,
            },
        ).mappings().first()
        report["enrichment_attempts_9h"] = {
            "subscriber": {"count": int(sub_att["n"] or 0), "last_utc": _fmt(sub_att["last_at"])},
            "format": {"count": int(fmt_att["n"] or 0), "last_utc": _fmt(fmt_att["last_at"])},
        }

        # Budget ledger today UTC
        day = now.strftime("%Y-%m-%d")
        budget = session.execute(
            text(
                """
                SELECT budget_kind, utc_day, id_units_reserved, http_requests
                FROM radar_api_budget_daily
                WHERE utc_day = :day
                ORDER BY budget_kind
                """
            ),
            {"day": day},
        ).mappings().all()
        limits = {
            "subscriber": int(os.environ.get("CHANNEL_SUBSCRIBER_ENRICHMENT_DAILY_LIMIT", "1000")),
            "format": int(os.environ.get("UNKNOWN_FORMAT_ENRICHMENT_DAILY_VIDEO_LIMIT", "1000")),
        }
        report["budget_utc_day"] = {
            "day": day,
            "rows": [
                {
                    "budget_kind": r["budget_kind"],
                    "utc_day": str(r["utc_day"]),
                    "id_units_reserved": int(r["id_units_reserved"] or 0),
                    "http_requests": int(r["http_requests"] or 0),
                }
                for r in budget
            ],
            "env_limits": limits,
        }

        # Read models
        att = session.execute(
            text(
                """
                SELECT run_id, computed_at, winner_count, candidate_video_count, pattern_count
                FROM attention_runs
                ORDER BY computed_at DESC NULLS LAST
                LIMIT 3
                """
            ),
        ).mappings().all()
        kp = session.execute(
            text(
                """
                SELECT run_id, evaluated_at, global_eligible_video_count, ranking_version
                FROM keyword_performance_global_snapshots
                ORDER BY evaluated_at DESC NULLS LAST
                LIMIT 3
                """
            ),
        ).mappings().all()
        kp_kw = session.execute(
            text("SELECT COUNT(*) AS n FROM keyword_performance_keyword_snapshots"),
        ).scalar()
        report["read_models"] = {
            "attention_last_3": [
                {
                    "run_id": r["run_id"],
                    "computed_utc": _fmt(r["computed_at"]),
                    "winner_count": r.get("winner_count"),
                    "candidate_video_count": r.get("candidate_video_count"),
                }
                for r in att
            ],
            "kp_global_last_3": [
                {
                    "run_id": r["run_id"],
                    "evaluated_utc": _fmt(r["evaluated_at"]),
                    "global_eligible_video_count": r.get("global_eligible_video_count"),
                }
                for r in kp
            ],
            "kp_keyword_rows_total": int(kp_kw or 0),
        }

        # Monitoring dry-run style counts (in-process, no YouTube)
        from app.services.metrics import utc_now as app_now
        from app.services.monitoring_api_service import build_active_monitoring_enriched
        from app.services.monitoring_tier_budget_policy import ApiBudgetPolicy
        from app.services.monitoring_cycle import run_monitoring_cycle

        class _NoNetwork:
            def get_videos(self, video_ids: list[str]):
                raise RuntimeError("audit_no_network")

        ref = app_now()
        enriched, tier_counts, unmon = build_active_monitoring_enriched(session, now=ref)
        dry = run_monitoring_cycle(
            session,
            youtube_client=_NoNetwork(),
            dry_run=True,
            current_time=ref,
        )
        report["monitoring_planner_dry_run"] = {
            "note": "dry_run=True, no DB writes, no HTTP",
            "loaded_video_count": dry.loaded_video_count,
            "eligible_video_count": dry.eligible_video_count,
            "due_count": dry.due_count,
            "overdue_count": dry.overdue_count,
            "capture_request_count": dry.capture_request_count,
            "selected_request_count": dry.selected_request_count,
            "deferred_request_count": dry.deferred_request_count,
            "tier_counts": dry.tier_counts,
            "cycle_status": dry.cycle_status,
            "enriched_active_count": len(enriched),
            "unmonitored_count": unmon,
            "tier_counts_enriched": tier_counts,
        }

        # Eligibility breakdown sample (read-only SQL approximations)
        from app.models.orm import Channel, Video, VideoFormat
        from app.services.monitoring_video_source import load_monitored_video_states
        from app.services.radar_target_eligibility import radar_target_rejection_reason

        states = load_monitored_video_states(session, now=ref, max_videos=5000)
        from app.services.video_format_api_verification import load_api_format_confirmed_video_ids

        confirmed = load_api_format_confirmed_video_ids(session, [s.video_id for s in states[:500]])
        breakdown: dict[str, int] = {}
        for st in states[:500]:
            vid = session.get(Video, st.video_id)
            if vid is None:
                breakdown["video_missing"] = breakdown.get("video_missing", 0) + 1
                continue
            ch = session.get(Channel, vid.channel_id) if vid.channel_id else None
            latest = session.execute(
                text(
                    "SELECT id FROM video_snapshots WHERE video_id=:v ORDER BY captured_at DESC LIMIT 1"
                ),
                {"v": st.video_id},
            ).first()
            snap = None
            if latest:
                from app.models.orm import VideoSnapshot as VS

                snap = session.get(VS, int(latest[0]))
            reason = radar_target_rejection_reason(
                content_format=vid.content_format,
                channel=ch,
                latest_snapshot=snap,
            )
            if reason:
                breakdown[reason] = breakdown.get(reason, 0) + 1
            elif vid.content_format in (VideoFormat.MEDIUM, VideoFormat.LONG) and vid.id not in confirmed:
                breakdown["format_unconfirmed"] = breakdown.get("format_unconfirmed", 0) + 1
            else:
                breakdown["eligible_load_path"] = breakdown.get("eligible_load_path", 0) + 1

        report["monitoring_eligibility_breakdown_sample"] = {
            "states_loaded": len(states),
            "sample_size": min(500, len(states)),
            "reasons": breakdown,
        }

    finally:
        session.close()

    report["log_tail_hints"] = {
        "discovery": _read_log_tail("discovery", 15),
        "monitoring": _read_log_tail("monitoring", 15),
    }

    out_path = ROOT / "artifacts" / "radar_inactivity_audit.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
