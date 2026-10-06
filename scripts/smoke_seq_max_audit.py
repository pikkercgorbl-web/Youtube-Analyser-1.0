#!/usr/bin/env python3
"""Read-only: compare max(id) vs sequence last_value in restore DB."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from migrate import load_dotenv
from sqlalchemy import create_engine, text
from urllib.parse import quote

RESTORE = "youtube_radar_restore_check"


def local_url(db: str) -> str:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env.docker")
    u = os.environ["RADAR_LOCAL_DB_USER"].strip()
    p = quote(os.environ["RADAR_LOCAL_DB_PASSWORD"].strip(), safe="")
    return f"postgresql://{u}:{p}@127.0.0.1:5433/{db}"


def main() -> None:
    eng = create_engine(local_url(RESTORE), pool_pre_ping=True)
    with eng.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT c.relname AS table_name,
                       a.attname AS column_name,
                       pg_get_serial_sequence(format('%I.%I', 'public', c.relname), a.attname) AS seq
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_attribute a ON a.attrelid = c.oid
                WHERE n.nspname = 'public'
                  AND c.relkind = 'r'
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                  AND pg_get_serial_sequence(format('%I.%I', 'public', c.relname), a.attname) IS NOT NULL
                ORDER BY c.relname;
                """
            )
        ).fetchall()
        report = []
        lagging = []
        for table, col, seq in rows:
            mx = conn.execute(
                text(f'SELECT COALESCE(MAX("{col}"), 0) FROM public."{table}"')
            ).scalar_one()
            lv = conn.execute(
                text("SELECT last_value FROM pg_sequences WHERE schemaname='public' AND sequencename = :s"),
                {"s": seq.split(".")[-1] if seq else ""},
            ).scalar_one_or_none()
            item = {
                "table": table,
                "column": col,
                "max_id": int(mx),
                "seq_last_value": int(lv) if lv is not None else None,
            }
            if lv is not None and int(lv) < int(mx):
                item["lag"] = int(mx) - int(lv)
                lagging.append(item)
            report.append(item)
        # startup side-effect predictors (read-only)
        backfill_candidates = conn.execute(
            text(
                """
                SELECT count(*) FROM target_keywords
                WHERE lifecycle_status IS NULL OR lifecycle_status = ''
                   OR source_type IS NULL OR source_type = ''
                   OR next_scan_at IS NULL
                   OR scan_interval_seconds IS NULL
                   OR status_changed_at IS NULL;
                """
            )
        ).scalar_one()
        placeholders = conn.execute(
            text(
                """
                SELECT count(*) FROM explosive_channels
                WHERE channel_id = '' OR channel_id ILIKE 'placeholder%'
                   OR channel_name ILIKE 'placeholder%';
                """
            )
        ).scalar_one()
    print(
        json.dumps(
            {
                "serial_columns": report,
                "sequences_lagging_max_id": lagging,
                "target_keywords_backfill_candidate_rows": int(backfill_candidates),
                "explosive_placeholder_like_rows": int(placeholders),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
