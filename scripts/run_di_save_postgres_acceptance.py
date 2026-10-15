"""Provision isolated PostgreSQL test DB and run DI save acceptance (Stage 1.23B.3).

Never targets youtube_radar_restore_check. Requires .env DATABASE_URL only to derive host/credentials.
Set DI_SAVE_POSTGRES_TEST_URL explicitly to skip auto-provision.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parents[1]
TEST_DB_NAME = "youtube_radar_di_save_test"

FORBIDDEN_DB_NAMES = frozenset(
    {
        "youtube_radar_restore_check",
        "youtube_radar",
        "postgres",
    },
)


def _load_dotenv_database_url() -> str | None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return os.environ.get("DATABASE_URL", "").strip() or None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _db_name_from_url(url: str) -> str:
    path = urlparse(url).path.lstrip("/")
    return path.split("?")[0] if path else ""


def _replace_db_name(url: str, db_name: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{db_name}"))


def _assert_safe_test_url(url: str) -> None:
    low = url.lower()
    if "restore_check" in low:
        raise SystemExit("Refusing URL containing restore_check")
    name = _db_name_from_url(url)
    if name in FORBIDDEN_DB_NAMES:
        raise SystemExit(f"Refusing forbidden database name: {name}")
    if name != TEST_DB_NAME and "_test" not in name and "test_" not in name:
        raise SystemExit(f"Refusing non-test database name: {name}")
    prod = _load_dotenv_database_url() or os.environ.get("DATABASE_URL", "").strip()
    if prod and url.split("@")[-1] == prod.split("@")[-1]:
        raise SystemExit("Test URL must not equal production DATABASE_URL path")


def _ensure_test_database(source_url: str) -> str:
    test_url = _replace_db_name(source_url, TEST_DB_NAME)
    _assert_safe_test_url(test_url)
    if _db_name_from_url(source_url) == TEST_DB_NAME:
        raise SystemExit("Source DATABASE_URL must not already be the test database")

    from sqlalchemy import create_engine, text

    admin_url = _replace_db_name(source_url, "postgres")
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": TEST_DB_NAME},
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    engine.dispose()
    return test_url


def main() -> int:
    explicit = os.environ.get("DI_SAVE_POSTGRES_TEST_URL", "").strip()
    if explicit:
        _assert_safe_test_url(explicit)
        test_url = explicit
        print(f"Using DI_SAVE_POSTGRES_TEST_URL database: {_db_name_from_url(test_url)}")
    else:
        source = _load_dotenv_database_url()
        if not source or "postgresql" not in source.lower():
            print("FAIL: no PostgreSQL DATABASE_URL in .env and no DI_SAVE_POSTGRES_TEST_URL")
            return 1
        src_name = _db_name_from_url(source)
        if src_name == "youtube_radar_restore_check":
            print(
                f"Safety: deriving isolated DB {TEST_DB_NAME} from host in .env (not using {src_name})",
            )
        test_url = _ensure_test_database(source)
        os.environ["DI_SAVE_POSTGRES_TEST_URL"] = test_url
        print(f"Provisioned/verified test database: {TEST_DB_NAME}")

    env = os.environ.copy()
    env["DI_SAVE_POSTGRES_TEST_URL"] = test_url
    env.pop("DATABASE_URL", None)

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "test_daily_intelligence_save_acceptance_1_23b3.py"), "--postgres-only"],
        cwd=str(ROOT),
        env=env,
    )
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
