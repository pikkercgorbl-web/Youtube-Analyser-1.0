#!/usr/bin/env python3
"""Verify pg_restore into a new DB: schema present, row counts match pre-restore snapshot."""

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


def _mask_host_db(url: str) -> str:
    return url.split("@")[-1] if "@" in url else url


def _counts_via_psql(db_name: str, user: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for table in TABLES:
        cmd = [
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
            db_name,
            "-tAc",
            f"SELECT count(*) FROM {table}",
        ]
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            out[table] = -1
            continue
        raw = (result.stdout or "").strip()
        out[table] = int(raw) if raw.isdigit() else -1
    return out


def _load_snapshot(dump: Path) -> dict[str, int] | None:
    sidecar = dump.with_suffix(".counts.snapshot.json")
    if not sidecar.is_file():
        alt = dump.parent / (dump.stem + ".counts.snapshot.json")
        if alt.is_file():
            sidecar = alt
        else:
            return None
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    counts = payload.get("counts")
    return counts if isinstance(counts, dict) else None


def main() -> int:
    dump_path = os.environ.get("BACKUP_VERIFY_DUMP", str(ROOT / "backups" / "pre_saved_topics_1_22d_20261006.dump"))
    source_db = os.environ.get("BACKUP_VERIFY_SOURCE_DB", "youtube_radar_restore_check")
    target_db = os.environ.get("BACKUP_VERIFY_TARGET_DB", "youtube_radar_backup_verify")
    user = os.environ.get("RADAR_LOCAL_DB_USER", "radar")

    dump = Path(dump_path)
    if not dump.is_file():
        print(json.dumps({"ok": False, "error": f"dump not found: {dump}"}))
        return 1

    subprocess.run(
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
            "postgres",
            "-c",
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{target_db}' AND pid <> pg_backend_pid();",
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    subprocess.run(
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
            "postgres",
            "-c",
            f"DROP DATABASE IF EXISTS {target_db};",
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
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
            "postgres",
            "-c",
            f"CREATE DATABASE {target_db} OWNER {user};",
        ],
        cwd=ROOT,
        check=True,
    )

    expected_counts = _load_snapshot(dump)
    source_counts = _counts_via_psql(source_db, user)
    if expected_counts is None:
        expected_counts = source_counts
        reference = "live_source"
    else:
        reference = "sidecar_snapshot"

    with dump.open("rb") as handle:
        restore = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                str(ROOT / ".env.docker"),
                "exec",
                "-T",
                "db",
                "pg_restore",
                "-U",
                user,
                "-d",
                target_db,
                "--no-owner",
                "--role=" + user,
            ],
            cwd=ROOT,
            stdin=handle,
            capture_output=True,
        )
    if restore.returncode != 0:
        err = (restore.stderr or b"").decode(errors="replace")[-2000:]
        print(json.dumps({"ok": False, "error": "pg_restore failed", "stderr_tail": err}))
        return 1

    target_counts = _counts_via_psql(target_db, user)
    mismatches = {
        table: {"expected": expected_counts.get(table), "restored": target_counts.get(table)}
        for table in TABLES
        if expected_counts.get(table) != target_counts.get(table)
    }
    # Tables absent in older dumps (-1 expected vs restored -1) are OK
    mismatches = {
        k: v
        for k, v in mismatches.items()
        if not (v.get("expected") == -1 and v.get("restored") == -1)
    }
    report = {
        "ok": restore.returncode == 0 and not mismatches,
        "pg_restore_exit_code": restore.returncode,
        "count_reference": reference,
        "source_db": source_db,
        "target_db": target_db,
        "dump": str(dump.name),
        "live_source_counts": source_counts,
        "expected_counts": expected_counts,
        "restored_counts": target_counts,
        "mismatches": mismatches,
    }
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
