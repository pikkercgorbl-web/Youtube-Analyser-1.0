#!/usr/bin/env python3
"""Write table row counts for backup verification sidecar."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = (
    "videos",
    "channels",
    "target_keywords",
    "attention_runs",
    "saved_topics",
    "saved_topic_observations",
    "saved_topic_events",
    "saved_topic_feedback",
)


def main() -> int:
    db = os.environ.get("SNAPSHOT_DB", "youtube_radar_restore_check")
    user = os.environ.get("RADAR_LOCAL_DB_USER", "radar")
    out = Path(os.environ.get("SNAPSHOT_OUT", ROOT / "backups" / "latest.counts.snapshot.json"))
    counts: dict[str, int] = {}
    for table in TABLES:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                str(ROOT / ".env.docker"),
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                user,
                "-d",
                db,
                "-tAc",
                f"SELECT count(*) FROM {table}",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            counts[table] = -1
        else:
            raw = (result.stdout or "").strip()
            counts[table] = int(raw) if raw.lstrip("-").isdigit() else -1
    payload = {"database": db, "counts": counts}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
