#!/usr/bin/env python3
"""Start uvicorn with DATABASE_URL from .env.docker (password not printed)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from migrate import load_dotenv

RESTORE = "youtube_radar_restore_check"
HOST = "127.0.0.1"
PORT = "8001"


def build_url() -> str:
    load_dotenv(ROOT / ".env.docker")
    user = os.environ["RADAR_LOCAL_DB_USER"].strip()
    pw = quote(os.environ["RADAR_LOCAL_DB_PASSWORD"].strip(), safe="")
    return f"postgresql://{user}:{pw}@{HOST}:5433/{RESTORE}"


def main() -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = build_url()
    # Do not load project .env over this if already set — child inherits only env copy
    env.pop("DOTENV", None)
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        HOST,
        "--port",
        PORT,
    ]
    subprocess.run(cmd, cwd=ROOT, env=env)


if __name__ == "__main__":
    main()
