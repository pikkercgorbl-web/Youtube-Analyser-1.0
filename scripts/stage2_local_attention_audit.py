"""One-shot Attention compute on local restore DB; prints eligibility stats (no YouTube API)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

RESTORE = "youtube_radar_restore_check"


def _database_url() -> str:
    load_dotenv(ROOT / ".env.docker")
    user = os.environ["RADAR_LOCAL_DB_USER"].strip()
    pw = quote(os.environ["RADAR_LOCAL_DB_PASSWORD"].strip(), safe="")
    return f"postgresql://{user}:{pw}@127.0.0.1:5433/{RESTORE}"


def main() -> int:
    os.environ["DATABASE_URL"] = _database_url()
    from sqlalchemy import func, select, text

    from app.models.db import SessionLocal, engine
    from app.models.orm import AttentionRun, Channel, Video, VideoFormat
    from app.services.attention_engine_service import compute_attention_engine
    from app.services.attention_engine_types import AttentionEngineConfig
    from app.services.radar_target_eligibility import resolve_known_subscribers
    from app.services.video_snapshot_storage import get_latest_snapshots_for_videos

    engine.echo = False
    session = SessionLocal()
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        print("local_restore_db=unavailable")
        return 1

    def counts() -> dict[str, int]:
        snap = session.scalar(select(func.count()).select_from(AttentionRun))
        unknown = session.scalar(
            select(func.count()).select_from(Video).where(Video.content_format == VideoFormat.UNKNOWN),
        )
        return {"attention_snapshots": int(snap or 0), "unknown_videos_total": int(unknown or 0)}

    before = counts()
    prev = session.execute(
        select(AttentionRun).order_by(AttentionRun.computed_at.desc()).limit(1),
    ).scalar_one_or_none()
    prev_winners = prev.winner_count if prev else None
    prev_patterns = prev.pattern_count if prev else None
    prev_families = None
    if prev and prev.notes_json:
        import json

        notes = json.loads(prev.notes_json)
        prev_families = notes.get("pattern_family_count")

    result = compute_attention_engine(session, config=AttentionEngineConfig(), source="stage2_audit")
    elig = result.summary.notes.get("radar_target_eligibility", {})
    print("before", before)
    print(
        "previous_snapshot",
        {
            "winners": prev_winners,
            "patterns": prev_patterns,
            "families": prev_families,
            "channels": prev.channel_momentum_count if prev else None,
        },
    )
    print(
        "after_compute",
        {
            "candidates": result.summary.candidate_video_count,
            "winners": result.summary.winner_count,
            "patterns": result.summary.pattern_count,
            "families": len(result.families),
            "channels": result.summary.channel_momentum_count,
        },
    )
    print("radar_target_eligibility", elig)
    print("unknown_videos_total", before["unknown_videos_total"])
    winner_ids = [w.video_id for w in result.video_winners[:10]]
    latest = get_latest_snapshots_for_videos(session, winner_ids)
    print("top10_computed_winners")
    for w in result.video_winners[:10]:
        ch = session.get(Channel, w.channel_id)
        snap = latest.get(w.video_id)
        subs = resolve_known_subscribers(channel=ch, latest_snapshot=snap)
        if snap is not None and snap.subscribers is not None:
            sub_src = "video_snapshot.subscribers"
        elif ch is not None and int(ch.subscribers_count or 0) > 0:
            sub_src = "channel.subscribers_count"
        else:
            sub_src = "unknown"
        vid = session.get(Video, w.video_id)
        fmt = vid.content_format.value if vid else "?"
        fmt_src = "videos.content_format (discovery/InnerTube or prior persist; not API in this run)"
        print(
            {
                "video_id": w.video_id,
                "channel_id": w.channel_id,
                "subscribers": subs,
                "subscriber_source": sub_src,
                "content_format": fmt,
                "format_source": fmt_src,
                "vph": w.vph,
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
