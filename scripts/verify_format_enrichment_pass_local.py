#!/usr/bin/env python3
"""One dry-run + one live enrichment pass + repeat dry-run on local working DB."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

ARTIFACT = ROOT / "artifacts" / "format_enrichment_pass_verify.json"


def main() -> int:
    load_dotenv(ROOT / ".env")
    from app.db.migrations import run_startup_migrations
    from app.models.db import SessionLocal, engine
    from app.services.radar_api_budget import enrichment_daily_budget_summary
    from app.services.radar_enrichment_orchestrator import run_radar_enrichment_pass
    from app.services.radar_enrichment_selection import RadarEnrichmentPassContext

    run_startup_migrations(engine)
    engine.echo = False
    session = SessionLocal()
    report: dict = {"generated_at": datetime.now(timezone.utc).isoformat()}
    try:
        now = datetime.now(timezone.utc)
        ctx = RadarEnrichmentPassContext(pass_sequence=int(now.timestamp()) % 10_000)

        class _DryRunClient:
            def get_channels(self, channel_ids: list[str]):
                return {}

            def get_videos(self, video_ids: list[str]):
                return []

        dry1 = run_radar_enrichment_pass(
            session,
            _DryRunClient(),
            context=ctx,
            dry_run=True,
            now=now,
        )
        session.rollback()
        report["dry_run_before"] = {
            "pass_report": asdict(dry1),
            "budget": enrichment_daily_budget_summary(session, now=now),
        }

        from app.api.deps import get_youtube_client

        live = run_radar_enrichment_pass(
            session,
            get_youtube_client(),
            context=ctx,
            dry_run=False,
            now=now,
        )
        session.commit()
        report["live_pass"] = {
            "pass_report": asdict(live),
            "budget": enrichment_daily_budget_summary(session, now=now),
        }

        dry2 = run_radar_enrichment_pass(
            session,
            _DryRunClient(),
            context=ctx,
            dry_run=True,
            now=now,
        )
        session.rollback()
        report["dry_run_after"] = {
            "pass_report": asdict(dry2),
            "budget": enrichment_daily_budget_summary(session, now=now),
        }

        planned_before = set()
        for note_key in ("subscriber_batches",):
            batches = (dry1.notes.get(note_key) or []) if hasattr(dry1, "notes") else []
            for b in batches:
                if isinstance(b, dict) and b.get("channel_ids"):
                    planned_before.update(b["channel_ids"])
        fmt_before = dry1.format_videos_planned
        fmt_after = dry2.format_videos_planned
        profile = (dry1.notes or {}).get("format_selection_profile") or {}
        report["checks"] = {
            "dry1_format_planned_at_least_50": fmt_before >= 50,
            "dry1_format_planned": fmt_before,
            "live_format_processed": live.format_videos_processed,
            "live_subscriber_processed": live.subscriber_channels_processed,
            "live_http_batches": {
                "channels": live.subscriber_http_batches,
                "videos": live.format_http_batches,
            },
            "format_selection_sql_profile": profile,
            "dry2_format_planned": fmt_after,
            "immediate_repeat_overlap_not_asserted": (
                "cooldown applies to missing/failed; confirmed/updated videos drop from queue"
            ),
        }
        report["tests"] = _run_regression_subprocess()
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps(report, indent=2, default=str))
        ok = report["checks"]["dry1_format_planned_at_least_50"]
        return 0 if ok else 1
    finally:
        session.close()


def _run_regression_subprocess() -> dict:
    import subprocess

    procs = [
        [sys.executable, str(ROOT / "scripts" / "test_format_enrichment_selection_regression.py")],
        [sys.executable, str(ROOT / "scripts" / "test_radar_enrichment_stage25.py")],
    ]
    out = {}
    for cmd in procs:
        name = Path(cmd[1]).name
        completed = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        out[name] = {
            "exit_code": completed.returncode,
            "stdout_tail": completed.stdout[-800:] if completed.stdout else "",
            "stderr_tail": completed.stderr[-400:] if completed.stderr else "",
        }
    return out


if __name__ == "__main__":
    raise SystemExit(main())
