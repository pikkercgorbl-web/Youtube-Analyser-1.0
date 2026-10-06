#!/usr/bin/env python3
"""Dry-run or apply videos.list published_at refinement for Radar pools."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Call YouTube videos.list and update DB")
    parser.add_argument("--dry-run", action="store_true", help="Plan only (default unless --apply)")
    args = parser.parse_args()
    dry_run = not args.apply

    load_dotenv(ROOT / ".env")
    from app.core.config import settings
    from app.integrations.youtube.client import YouTubeApiClient
    from app.integrations.youtube.key_manager import YouTubeApiKeyManager
    from app.models.db import SessionLocal
    from app.services.published_at_refinement import apply_published_at_refinement
    from app.services.metrics import utc_now

    session = SessionLocal()
    client: YouTubeApiClient | None = None
    if not dry_run:
        if not settings.youtube_api_keys:
            print("No YOUTUBE_API_KEYS configured; use --dry-run or set keys in .env")
            return 1
        client = YouTubeApiClient(YouTubeApiKeyManager(settings.youtube_api_keys))

    class _DryRunClient:
        def get_videos(self, video_ids: list[str]) -> list[object]:
            return []

    now = utc_now()
    totals = {
        "videos_updated": 0,
        "videos_unchanged": 0,
        "videos_missing": 0,
        "videos_failed": 0,
        "budget_units_reserved": 0,
        "http_batches_executed": 0,
    }
    report = None
    pass_num = 0
    while True:
        pass_num += 1
        report = apply_published_at_refinement(
            session,
            client if client is not None else _DryRunClient(),
            dry_run=dry_run,
            now=now,
        )
        for key in totals:
            totals[key] += int(getattr(report, key, 0) or 0)
        if dry_run or report.quota_exhausted or report.selected_video_count == 0:
            break
        if (report.pool_remaining_after or 0) == 0:
            break
        if (report.daily_budget_remaining_after or 0) == 0:
            break
        if pass_num >= 20:
            break
    if report is not None:
        for key, val in totals.items():
            setattr(report, key, val)

    out = ROOT / "artifacts" / "published_at_refinement_report.json"
    out.parent.mkdir(exist_ok=True)
    payload = asdict(report)
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    summary = {k: payload.get(k) for k in (
        "dry_run",
        "daily_budget_limit",
        "daily_budget_remaining",
        "daily_budget_remaining_after",
        "pool_video_count",
        "pool_remaining_after",
        "selected_video_count",
        "api_batches",
        "http_batches_executed",
        "deferred_to_next_day",
        "videos_updated",
        "videos_unchanged",
        "videos_missing",
        "videos_failed",
        "quota_exhausted",
        "budget_units_reserved",
    )}
    summary["passes_run"] = pass_num
    print(json.dumps(summary, indent=2))
    if payload.get("quota_exhausted"):
        print("STOPPED: YouTube quota or API limit error.", payload.get("notes", {}).get("last_error"))
        session.close()
        return 2
    print(f"written={out}")
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
