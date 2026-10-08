"""One-shot evidence capture before worker restart (read-only)."""

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


def _database_url() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("DATABASE_URL missing")


def main() -> int:
    url = _database_url()
    p = urlparse(url)
    evidence: dict = {
        "captured_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "database": {"host": p.hostname, "port": p.port, "database": p.path.lstrip("/")},
    }
    try:
        import psycopg2

        conn = psycopg2.connect(
            host=p.hostname,
            port=p.port,
            dbname=p.path.lstrip("/"),
            user=p.username,
            password=p.password,
        )
        cur = conn.cursor()
        cur.execute(
            """
            SELECT pid, state, wait_event_type, wait_event, query_start,
                   left(query, 220) AS query_prefix,
                   EXTRACT(EPOCH FROM (now() - query_start)) AS query_age_s
            FROM pg_stat_activity
            WHERE datname = %s AND pid <> pg_backend_pid()
              AND state IS DISTINCT FROM 'idle'
            ORDER BY query_start NULLS LAST
            """,
            (p.path.lstrip("/"),),
        )
        evidence["pg_stat_activity"] = [
            {
                "pid": r[0],
                "state": r[1],
                "wait_event_type": r[2],
                "wait_event": r[3],
                "query_start": r[4].isoformat() if r[4] else None,
                "query_prefix": r[5],
                "query_age_s": float(r[6] or 0),
            }
            for r in cur.fetchall()
        ]
        cur.execute(
            """
            SELECT blocked.pid, blocked.state, blocking.pid AS blocking_pid,
                   left(blocked.query, 160) AS blocked_q
            FROM pg_stat_activity blocked
            JOIN pg_stat_activity blocking ON blocking.pid = ANY(pg_blocking_pids(blocked.pid))
            WHERE blocked.datname = %s
            """,
            (p.path.lstrip("/"),),
        )
        evidence["blocking"] = [
            {
                "blocked_pid": r[0],
                "state": r[1],
                "blocking_pid": r[2],
                "blocked_q_prefix": r[3],
            }
            for r in cur.fetchall()
        ]
        conn.close()
    except Exception as exc:
        evidence["pg_error"] = str(exc)

    try:
        import psutil

        targets = ("run_monitoring_worker", "run_outcome_capture_worker")
        evidence["processes"] = []
        for proc in psutil.process_iter(["pid", "name", "create_time", "cmdline"]):
            try:
                cmd = " ".join(proc.info["cmdline"] or [])
                if any(t in cmd for t in targets):
                    evidence["processes"].append(
                        {"pid": proc.info["pid"], "cmdline": cmd[:240]},
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception as exc:
        evidence["psutil_error"] = str(exc)

    out = ROOT / "artifacts" / "monitoring_stall_evidence_pre_fix.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
