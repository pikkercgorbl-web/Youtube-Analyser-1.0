"""One-shot radar scan for Stage 1.2 signal snapshot verification."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.services.explosive_channels_radar_worker as radar_module
from app.models.db import SessionLocal
from app.services.explosive_channels_radar_worker import ExplosiveChannelsRadarWorker
from app.services.target_keywords_service import (
    WORKER_STATUS_IDLE,
    TargetKeywordsService,
)


async def main() -> None:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "AI tools"
    worker = ExplosiveChannelsRadarWorker()
    db = SessionLocal()
    try:
        if TargetKeywordsService().is_worker_stopped(db):
            TargetKeywordsService().set_worker_status(db, WORKER_STATUS_IDLE)

        radar_module.is_radar_running = True
        try:
            await worker.run_manual_scan(keyword)
        finally:
            radar_module.is_radar_running = False
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
