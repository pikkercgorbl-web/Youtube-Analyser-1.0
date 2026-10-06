#!/usr/bin/env python3
"""Dry-run plan: format enrichment for 19 audit channels (no API/workers)."""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

AUDIT_CHANNEL_IDS = [
    "UCYuRFMgWVnuWE1PIkB6a-wA",
    "UCqJZ2Udkbr3DxBNaL9B32gQ",
    "UCauQiaWUYLUE0kxxpqO3s8g",
    "UCitc82QwQ1PMUimoUJ3RjOQ",
    "UCNayrcQlCP-OCaHuiO2BW0w",
    "UCaJFV7a5lTixtHLXft0yM0w",
    "UCa1cwdXmhc66DTa6HWbxt3g",
    "UC3eVR9HV3X363M0uuESgwDw",
    "UC4Ys8N_QLOiJiFWnNBDRcOQ",
    "UCLKeV3CTe5pfFiuKWaVLXiQ",
    "UCGEq3OUr7NEBRd_k_NSfQTw",
    "UCM5PsLystlm5bVMk3kCA2DQ",
    "UCsUJle6Mb-km0qhYvQ0ymSQ",
    "UCiU1z9haraEXGPduIk0iHOw",
    "UCtgI0nZA4pxHI84M7Qj2gmw",
    "UCZJ6_SRCGITZPLA-WLypYJA",
    "UCJ5olPxnsfClcBSvyv1aJHg",
    "UCRFFm4C4CMVGBGsIVM7HMww",
    "UClo83tLttrq5kS59QqAY3iw",
]

VIDEOS_LIST_BATCH = 50


def main() -> int:
    load_dotenv = __import__("migrate", fromlist=["load_dotenv"]).load_dotenv
    load_dotenv(ROOT / ".env")
    from app.models.db import SessionLocal
    from app.models.orm import Video, VideoFormat
    from app.services.attention_engine_types import AttentionEngineConfig
    from app.services.metrics import utc_now
    from app.services.radar_api_budget import BUDGET_KIND_VIDEOS_LIST, utc_calendar_day
    from app.services.radar_enrichment_config import radar_enrichment_settings
    from app.services.video_format_api_verification import load_api_format_confirmed_video_ids

    session = SessionLocal()
    now = utc_now()
    cfg = AttentionEngineConfig()
    end = now
    start = end - timedelta(days=cfg.channel_recent_days + cfg.channel_previous_days)

    from sqlalchemy import select

    videos = list(
        session.scalars(
            select(Video).where(
                Video.channel_id.in_(AUDIT_CHANNEL_IDS),
                Video.published_at >= start,
                Video.published_at <= end,
            ),
        ).all(),
    )
    all_ids = [v.id for v in videos]
    confirmed = load_api_format_confirmed_video_ids(session, all_ids)
    need_format = [
        v.id
        for v in videos
        if v.content_format in (VideoFormat.MEDIUM, VideoFormat.LONG) and v.id not in confirmed
    ]
    settings = radar_enrichment_settings
    day = utc_calendar_day(now)
    from app.services.radar_api_budget import budget_day_status, remaining_id_units
    from app.services.unknown_format_enrichment_config import unknown_format_enrichment_settings

    daily_limit = unknown_format_enrichment_settings.unknown_format_enrichment_daily_video_limit
    budget_row = budget_day_status(session, budget_kind=BUDGET_KIND_VIDEOS_LIST, now=now)
    reserved = int(budget_row.id_units_reserved)
    remaining_budget = remaining_id_units(
        session,
        budget_kind=BUDGET_KIND_VIDEOS_LIST,
        daily_limit=daily_limit,
        now=now,
    )
    batches = (len(need_format) + VIDEOS_LIST_BATCH - 1) // VIDEOS_LIST_BATCH if need_format else 0

    plan = {
        "channels": len(AUDIT_CHANNEL_IDS),
        "videos_in_momentum_windows": len(all_ids),
        "unique_video_ids_needing_format_confirmation": len(need_format),
        "videos_list_batches_ceil": batches,
        "batch_size": VIDEOS_LIST_BATCH,
        "utc_day": day.isoformat(),
        "videos_list_budget_daily_limit": daily_limit,
        "videos_list_budget_reserved_today": reserved,
        "videos_list_budget_remaining_today": remaining_budget,
        "pass_limit_per_enrichment_pass": settings.video_format_enrichment_pass_limit,
        "note": "Format confirmation does not create historical snapshots; monitoring revisits still required for age-aligned VPH.",
        "suggested_pass_context": {
            "cycle_video_ids_count": len(need_format),
            "cycle_channel_ids_count": len(AUDIT_CHANNEL_IDS),
        },
    }
    out = ROOT / "artifacts" / "momentum_audit_format_enrichment_plan.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(json.dumps(plan, indent=2))
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
