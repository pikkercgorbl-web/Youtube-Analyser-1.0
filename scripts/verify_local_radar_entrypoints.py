#!/usr/bin/env python3
"""Smoke-check DB, migrations, backend import, optional HTTP — no workers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

EXPECTED_HOST = "127.0.0.1"
EXPECTED_PORT = 5433
EXPECTED_DB = "youtube_radar_restore_check"


def _mask_url(url: str) -> str:
    if "@" not in url:
        return url
    pre, rest = url.split("@", 1)
    if "://" in pre:
        scheme, _ = pre.split("://", 1)
        return f"{scheme}://***@{rest}"
    return f"***@{rest}"


def main() -> int:
    load_dotenv(ROOT / ".env")
    report: dict = {"ok": True, "checks": []}

    def add(name: str, ok: bool, detail: object) -> None:
        report["checks"].append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            report["ok"] = False

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        add("env_database_url", False, "DATABASE_URL missing in .env")
        print(json.dumps(report, indent=2))
        return 1

    masked = _mask_url(db_url)
    add(
        "env_database_url_target",
        EXPECTED_HOST in db_url and EXPECTED_DB in db_url,
        {"url": masked, "expected_db": EXPECTED_DB},
    )

    enrich = os.environ.get("RADAR_ENRICHMENT_AFTER_DISCOVERY", "")
    add(
        "radar_enrichment_flag",
        enrich.strip() in ("1", "true", "True", "yes"),
        {"RADAR_ENRICHMENT_AFTER_DISCOVERY": enrich or "(unset)"},
    )

    fmt_limit = os.environ.get("UNKNOWN_FORMAT_ENRICHMENT_DAILY_VIDEO_LIMIT", "")
    add(
        "videos_list_budget_env",
        bool(fmt_limit.strip()),
        {"UNKNOWN_FORMAT_ENRICHMENT_DAILY_VIDEO_LIMIT": fmt_limit or "(default 1000)"},
    )

    fe_api = (ROOT / "frontend" / ".env.local").read_text(encoding="utf-8") if (ROOT / "frontend" / ".env.local").is_file() else ""
    fe_url = "http://localhost:8000"
    for line in fe_api.splitlines():
        if line.startswith("NEXT_PUBLIC_API_URL="):
            fe_url = line.split("=", 1)[1].strip().strip('"')
            break
    add(
        "frontend_api_url",
        "8000" in fe_url and "127.0.0.1" in fe_url or "localhost" in fe_url,
        {"NEXT_PUBLIC_API_URL": fe_url},
    )

    from sqlalchemy import create_engine, text

    from app.db.migrations import run_startup_migrations

    try:
        engine = create_engine(db_url, pool_pre_ping=True)
        run_startup_migrations(engine)
        with engine.connect() as conn:
            db_name = conn.execute(text("select current_database()")).scalar_one()
            add("postgres_connect", db_name == EXPECTED_DB, {"current_database": db_name})
    except Exception as exc:
        add("postgres_connect", False, str(exc))
        print(json.dumps(report, indent=2, default=str))
        return 1

    try:
        from app.core.config import settings

        add("settings_load", True, {"app": settings.app_name})
    except Exception as exc:
        add("settings_load", False, str(exc))

    try:
        from app.models.db import SessionLocal

        session = SessionLocal()
        try:
            session.execute(text("select 1"))
            add("session_local", True, "select 1 ok")
        finally:
            session.close()
    except Exception as exc:
        add("session_local", False, str(exc))

    # Optional: short-lived uvicorn + /docs
    port = 8765
    env = os.environ.copy()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        ok_http = False
        detail = ""
        for _ in range(30):
            time.sleep(0.3)
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/docs", timeout=2) as resp:
                    ok_http = resp.status == 200
                    detail = f"GET /docs -> {resp.status}"
                    break
            except (urllib.error.URLError, TimeoutError):
                continue
        if not ok_http:
            detail = detail or "timeout waiting for /docs"
        add("backend_http_smoke", ok_http, detail)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/attention/summary", timeout=2) as resp:
            payload = json.loads(resp.read().decode())
        summary = payload.get("summary") or payload
        add(
            "attention_api_optional",
            True,
            {
                "run_id": summary.get("run_id"),
                "winners": summary.get("winner_count"),
            },
        )
    except Exception as exc:
        add(
            "attention_api_optional",
            True,
            f"skipped (no server on :8000): {exc}",
        )

    print(json.dumps(report, indent=2, default=str))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
