"""One-shot Attention Engine refresh (Stage 1.22A). No always-on worker."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.migrations import run_startup_migrations
from app.models.db import SessionLocal, engine
from app.services.attention_engine_service import compute_attention_engine
from app.services.attention_engine_types import (
    AttentionEngineConfig,
    attention_result_to_dict,
)
from app.services.attention_read_model import refresh_attention_engine


def _print_human(result) -> None:
    s = result.summary
    print("ATTENTION ENGINE")
    print(f"source={s.source} run_id={s.run_id} timezone={s.timezone_name}")
    print(f"window={s.window_start.isoformat()} .. {s.window_end.isoformat()} ({s.window_hours}h)")
    print(f"candidates={s.candidate_video_count} winners={s.winner_count} patterns={s.pattern_count} families={len(result.families)} channels={s.channel_momentum_count}")
    print("\nTop video winners:")
    for i, row in enumerate(result.video_winners[:10], start=1):
        print(f"  {i}. {row.video_id} {row.youtube_url}")
        print(f"     reasons: {'; '.join(row.human_reasons)}")
    print("\nTop pattern families:")
    for i, row in enumerate(result.families[:10], start=1):
        print(
            f"  {i}. {row.family_key} {row.label!r} videos={row.video_count} channels={row.channel_count} members={len(row.member_pattern_keys)} flags={list(row.quality_flags)}"
        )
    print("\nTop patterns:")
    for i, row in enumerate(result.patterns[:10], start=1):
        print(f"  {i}. {row.pattern_key} {row.label!r} videos={row.video_count} channels={row.channel_count}")
        print(f"     reasons: {'; '.join(row.human_reasons)}")
    print("\nTop channel momentum:")
    for i, row in enumerate(result.channels[:10], start=1):
        print(f"  {i}. {row.channel_id} {row.channel_title!r}")
        print(f"     reasons: {'; '.join(row.human_reasons)}")


def main(argv: list[str] | None = None) -> int:
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Refresh Attention Engine snapshot from existing Radar data.")
    parser.add_argument("--window-hours", type=int, default=24)
    parser.add_argument("--video-limit", type=int, default=50)
    parser.add_argument("--pattern-limit", type=int, default=20)
    parser.add_argument("--channel-limit", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true", help="Compute and print; do not persist.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a human summary.")
    args = parser.parse_args(argv)

    config = AttentionEngineConfig(
        window_hours=args.window_hours,
        video_limit=args.video_limit,
        pattern_limit=args.pattern_limit,
        channel_limit=args.channel_limit,
    )
    engine.echo = False
    run_startup_migrations(engine)
    session = SessionLocal()
    try:
        if args.dry_run:
            result = compute_attention_engine(session, config=config, source="live_compute")
        else:
            result = refresh_attention_engine(session, config=config)
            session.commit()
        if args.json:
            sys.stdout.reconfigure(encoding="utf-8")
            print(json.dumps(attention_result_to_dict(result), indent=2, default=str))
        else:
            _print_human(result)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
