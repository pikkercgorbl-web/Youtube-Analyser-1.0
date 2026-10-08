#!/usr/bin/env python3
"""Point app .env at local Docker Postgres (optional archive of prior remote URL)."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
BACKUP_DIR = ROOT / "backups" / "migration_archive"
BACKUP_FILE = BACKUP_DIR / "database_url_remote.env"
LEGACY_BACKUP = ROOT / ".env.supabase.remote"
LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 5433
LOCAL_DB = "youtube_radar_restore_check"


def _load_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, val = stripped.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def _build_local_database_url(docker_env: dict[str, str]) -> str:
    user = docker_env["RADAR_LOCAL_DB_USER"].strip()
    password = docker_env["RADAR_LOCAL_DB_PASSWORD"].strip()
    pw = quote(password, safe="")
    return f"postgresql://{user}:{pw}@{LOCAL_HOST}:{LOCAL_PORT}/{LOCAL_DB}"


def _is_local_database_url(url: str) -> bool:
    lower = url.lower()
    return LOCAL_HOST in lower and f":{LOCAL_PORT}/" in lower and LOCAL_DB in lower


def _is_postgres_url(url: str) -> bool:
    lower = url.lower()
    return "postgresql" in lower or lower.startswith("postgres://")


def _upsert_env_line(lines: list[str], key: str, value: str) -> list[str]:
    """Remove every existing KEY= line, append one canonical assignment."""
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    out = [line for line in lines if not pattern.match(line)]
    while out and not out[-1].strip():
        out.pop()
    if out and out[-1].strip():
        out.append("")
    out.append(f"{key}={value}")
    return out


def _ensure_remote_archive(current_url: str) -> None:
    if not current_url or _is_local_database_url(current_url) or not _is_postgres_url(current_url):
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if LEGACY_BACKUP.is_file() and not BACKUP_FILE.is_file():
        LEGACY_BACKUP.replace(BACKUP_FILE)
        print(f"Migrated legacy backup to {BACKUP_FILE.resolve()}")
    if BACKUP_FILE.is_file():
        print(f"Remote DATABASE_URL archive exists (not overwritten): {BACKUP_FILE.resolve()}")
        return
    BACKUP_FILE.write_text(
        "# Archived remote DATABASE_URL (hosted Postgres migration).\n"
        f"DATABASE_URL={current_url}\n",
        encoding="utf-8",
    )
    print(f"Archived prior remote DATABASE_URL to {BACKUP_FILE.resolve()}")


def main() -> int:
    env_path = ROOT / ".env"
    docker_path = ROOT / ".env.docker"

    if not docker_path.is_file():
        print("Missing .env.docker (RADAR_LOCAL_DB_USER/PASSWORD).", file=sys.stderr)
        return 1

    docker_env = _load_dotenv(docker_path)
    for req in ("RADAR_LOCAL_DB_USER", "RADAR_LOCAL_DB_PASSWORD"):
        if not docker_env.get(req):
            print(f"Missing {req} in .env.docker", file=sys.stderr)
            return 1

    local_url = _build_local_database_url(docker_env)

    if env_path.is_file():
        app_env = _load_dotenv(env_path)
        current = app_env.get("DATABASE_URL", "")
        if current and not _is_local_database_url(current):
            _ensure_remote_archive(current)
        elif current and _is_local_database_url(current):
            print("Current DATABASE_URL is already local; remote archive untouched.")
        lines = env_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = ["# Local Radar (see docs/LOCAL_RADAR_LAPTOP.md)"]

    lines = _upsert_env_line(lines, "DATABASE_URL", local_url)
    lines = _upsert_env_line(lines, "RADAR_ENRICHMENT_AFTER_DISCOVERY", "1")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Updated .env at {env_path.resolve()}")
    print(f"DATABASE_URL -> {LOCAL_HOST}:{LOCAL_PORT}/{LOCAL_DB}")
    print("Set RADAR_ENRICHMENT_AFTER_DISCOVERY=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
