#!/usr/bin/env python3
"""Offline Channel Momentum compute (no persist, no YouTube)."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv


def main() -> int:
    load_dotenv(ROOT / ".env")
    from datetime import timedelta

    from app.models.db import SessionLocal
    from app.services.attention_channel_momentum import (
        build_channel_momentum,
        diagnose_channel_momentum_candidates,
    )
    from app.services.attention_engine_types import AttentionEngineConfig, channel_momentum_to_dict
    from app.services.attention_evidence import load_attention_evidence
    from app.services.metrics import utc_now
    from app.services.video_format_api_verification import load_api_format_confirmed_video_ids

    session = SessionLocal()
    cfg = AttentionEngineConfig()
    now = utc_now()
    ws, we = now - timedelta(hours=cfg.window_hours), now
    lb = we - timedelta(days=cfg.channel_recent_days + cfg.channel_previous_days)
    bundle = load_attention_evidence(session, window_start=ws, window_end=we, channel_lookback_start=lb)
    all_ids = list(bundle.records.keys())
    for rows in bundle.extra_channel_videos.values():
        all_ids.extend(v.id for v in rows)
    confirmed = load_api_format_confirmed_video_ids(session, list(dict.fromkeys(all_ids)))
    channels = build_channel_momentum(
        bundle,
        cfg,
        now=now,
        publishable_confirmed_ids=confirmed,
    )
    diagnostics = diagnose_channel_momentum_candidates(
        bundle,
        cfg,
        now=now,
        publishable_confirmed_ids=confirmed,
    )
    diag_counts = Counter(code for _, code in diagnostics if code)
    report = {
        "computed_at": now.isoformat(),
        "published_signal_count": len(channels),
        "published_channels": [
            {
                "channel_id": row.channel_id,
                "title": row.channel_title,
                "recent_measurable": row.recent_measurable_count,
                "previous_measurable": row.previous_measurable_count,
                "recent_improvement_count": row.recent_improvement_count,
                "ratio": row.recent_median_vph_vs_previous,
                "reason_codes": list(row.reason_codes),
                "incompleteness_notes": list(row.incompleteness_notes),
            }
            for row in channels
        ],
        "rejection_primary_diagnostic_counts": dict(diag_counts),
        "channels": [channel_momentum_to_dict(row) for row in channels],
    }
    out = ROOT / "artifacts" / "channel_momentum_offline.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {"written": str(out), "published_signal_count": len(channels), "rejections": dict(diag_counts)},
            indent=2,
        ),
    )
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
