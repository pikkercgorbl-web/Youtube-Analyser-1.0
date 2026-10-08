#!/usr/bin/env python3
"""Read-only operations preflight for local restore-check (Stage 3)."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

ARTIFACT = ROOT / "artifacts" / "stage3_operations_preflight.json"


def _count_api_keys(raw: str) -> int:
    if not raw.strip():
        return 0
    return len([part for part in raw.replace("\n", ",").split(",") if part.strip()])


def main() -> int:
    load_dotenv(ROOT / ".env")
    from sqlalchemy.orm import sessionmaker

    from app.models.db import SessionLocal, engine
    from app.services.attention_read_model import get_latest_attention_run
    from app.services.keyword_performance_read_model import get_latest_global_snapshot
    from app.services.keyword_expansion_runtime_config import keyword_expansion_runtime_settings
    from app.services.radar_enrichment_config import radar_enrichment_settings
    from app.services.topic_exploration_runtime_config import topic_exploration_runtime_settings
    from app.services.unknown_format_enrichment_config import unknown_format_enrichment_settings

    engine.echo = False
    session = SessionLocal()
    now = datetime.now(timezone.utc)
    try:
        db_url = os.environ.get("DATABASE_URL", "")
        parsed = urlparse(db_url) if db_url else None
        host = parsed.hostname if parsed else None
        port = parsed.port if parsed else None
        db_name = parsed.path.lstrip("/") if parsed and parsed.path else None

        attention_run = get_latest_attention_run(session)
        kp_global = get_latest_global_snapshot(session)

        marker = ROOT / "artifacts" / "momentum_measurement_start.json"
        measurement_start = None
        if marker.is_file():
            measurement_start = json.loads(marker.read_text(encoding="utf-8")).get("measurement_start_utc")

        report = {
            "checked_at_utc": now.isoformat(),
            "database": {
                "host": host,
                "port": port,
                "name": db_name,
            },
            "enrichment": {
                "radar_enrichment_after_discovery": radar_enrichment_settings.radar_enrichment_after_discovery,
                "keyword_expansion_after_discovery": keyword_expansion_runtime_settings.keyword_expansion_after_discovery,
                "topic_exploration_in_discovery": topic_exploration_runtime_settings.topic_exploration_in_discovery,
                "topic_exploration_auto_admit": topic_exploration_runtime_settings.topic_exploration_auto_admit,
                "topic_exploration_queries_file": topic_exploration_runtime_settings.topic_exploration_queries_file,
                "channel_subscriber_daily_limit": radar_enrichment_settings.channel_subscriber_enrichment_daily_limit,
                "channel_subscriber_pass_limit": radar_enrichment_settings.channel_subscriber_enrichment_pass_limit,
                "video_format_pass_limit": radar_enrichment_settings.video_format_enrichment_pass_limit,
                "unknown_format_daily_limit": unknown_format_enrichment_settings.unknown_format_enrichment_daily_video_limit,
                "backlog_pass_fraction": radar_enrichment_settings.enrichment_backlog_pass_fraction,
            },
            "youtube_api_keys_count": _count_api_keys(os.environ.get("YOUTUBE_API_KEYS", "")),
            "read_models": {
                "attention_latest_computed_at": attention_run.computed_at.isoformat() if attention_run else None,
                "attention_run_id": attention_run.run_id if attention_run else None,
                "keyword_performance_evaluated_at": kp_global.evaluated_at.isoformat() if kp_global else None,
                "keyword_performance_run_id": kp_global.run_id if kp_global else None,
            },
            "launch_paths": {
                "start_backend": (ROOT / "scripts" / "start-backend.ps1").is_file(),
                "start_frontend": (ROOT / "scripts" / "start-frontend.ps1").is_file(),
                "run_discovery_worker": (ROOT / "scripts" / "run_discovery_worker.py").is_file(),
                "run_monitoring_worker": (ROOT / "scripts" / "run_monitoring_worker.py").is_file(),
                "refresh_attention": (ROOT / "scripts" / "refresh_attention_engine.py").is_file(),
                "refresh_keyword_performance": (ROOT / "scripts" / "backfill_keyword_performance_read_model.py").is_file(),
            },
            "logs_dir_exists": (ROOT / "logs" / "scheduled").exists(),
            "measurement_start_utc": measurement_start,
            "note": "Read-only; no workers started; secrets not printed.",
        }
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
