#!/usr/bin/env python3
"""
Migrate data from local SQLite (database.db) to PostgreSQL (any DATABASE_URL).

Usage:
    set DATABASE_URL=postgresql://user:pass@host:5432/dbname
    python migrate.py

Options:
    python migrate.py --sqlite database.db
    python migrate.py --dry-run
    python migrate.py --no-truncate
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, insert, text
from sqlalchemy.engine import Engine

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import normalize_database_url
from app.models.db import Base
import app.models.orm  # noqa: F401 — register ORM tables

DEFAULT_SQLITE_PATH = PROJECT_ROOT / "database.db"

# Parent tables first, then tables with foreign keys.
TABLES_IN_ORDER = [
    "channels",
    "channel_snapshots",
    "videos",
    "keywords",
    "saved_keywords",
    "explosive_channels",
    "explosive_channel_settings",
    "target_keywords",
    "radar_worker_state",
    "extended_search_cache",
    "video_snapshots",
]

TABLES_WITH_SERIAL_ID = (
    "channel_snapshots",
    "keywords",
    "saved_keywords",
    "target_keywords",
    "video_snapshots",
)


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE pairs from .env without overriding existing env vars."""
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_sqlite_url(sqlite_arg: str | None) -> str:
    if sqlite_arg:
        path = Path(sqlite_arg)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.is_file():
            raise SystemExit(f"ERROR: SQLite file not found: {path}")
        return f"sqlite:///{path.resolve().as_posix()}"

    env_url = os.environ.get("SQLITE_URL", "").strip()
    if env_url:
        return env_url

    if not DEFAULT_SQLITE_PATH.is_file():
        raise SystemExit(
            f"ERROR: SQLite file not found: {DEFAULT_SQLITE_PATH}\n"
            "Pass --sqlite path/to/database.db or set SQLITE_URL.",
        )
    return f"sqlite:///{DEFAULT_SQLITE_PATH.resolve().as_posix()}"


def resolve_postgres_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit(
            "ERROR: DATABASE_URL is required.\n"
            "Example: set DATABASE_URL=postgresql://user:pass@host:5432/postgres",
        )
    if url.startswith("sqlite"):
        raise SystemExit(
            "ERROR: DATABASE_URL points to SQLite. Set it to your PostgreSQL connection string.",
        )
    return normalize_database_url(url)


def mask_database_url(url: str) -> str:
    if "@" not in url:
        return url
    prefix, suffix = url.split("@", 1)
    if "://" in prefix:
        scheme, _, _credentials = prefix.partition("://")
        return f"{scheme}://***@{suffix}"
    return f"***@{suffix}"


def create_postgres_schema(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)


def table_exists(engine: Engine, table_name: str) -> bool:
    return table_name in inspect(engine).get_table_names()


def fetch_rows(engine: Engine, table_name: str) -> list[dict]:
    if not table_exists(engine, table_name):
        return []

    with engine.connect() as connection:
        result = connection.execute(text(f'SELECT * FROM "{table_name}"'))
        return [dict(row._mapping) for row in result]


def truncate_postgres(engine: Engine) -> None:
    existing = [name for name in reversed(TABLES_IN_ORDER) if table_exists(engine, name)]
    if not existing:
        return

    tables_sql = ", ".join(f'"{name}"' for name in existing)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {tables_sql} RESTART IDENTITY CASCADE"))


def copy_table(source: Engine, target: Engine, table_name: str) -> int:
    rows = fetch_rows(source, table_name)
    if not rows:
        print(f"  {table_name}: 0 rows")
        return 0

    if not table_exists(target, table_name):
        print(f"  {table_name}: skipped (table missing in PostgreSQL)")
        return 0

    table = Base.metadata.tables[table_name]
    with target.begin() as connection:
        connection.execute(insert(table), rows)

    print(f"  {table_name}: {len(rows)} rows copied")
    return len(rows)


def reset_sequences(engine: Engine) -> None:
    for table_name in TABLES_WITH_SERIAL_ID:
        if not table_exists(engine, table_name):
            continue

        with engine.begin() as connection:
            connection.execute(
                text(
                    f"SELECT setval("
                    f"pg_get_serial_sequence('{table_name}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM \"{table_name}\"), 1), "
                    f"true)",
                ),
            )
        print(f"  sequence updated: {table_name}.id")


def print_dry_run(source: Engine) -> None:
    total = 0
    print("Dry run - row counts in SQLite:")
    for table_name in TABLES_IN_ORDER:
        count = len(fetch_rows(source, table_name))
        print(f"  {table_name}: {count}")
        total += count
    print(f"Total: {total} rows")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy data from local SQLite (database.db) to PostgreSQL (DATABASE_URL).",
    )
    parser.add_argument(
        "--sqlite",
        metavar="PATH",
        help="Path to SQLite file (default: ./database.db in project root)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print row counts from SQLite, do not write to PostgreSQL",
    )
    parser.add_argument(
        "--no-truncate",
        action="store_true",
        help="Do not clear PostgreSQL tables before insert (may fail on duplicates)",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")

    args = parse_args()
    sqlite_url = resolve_sqlite_url(args.sqlite)
    postgres_url = resolve_postgres_url()

    print("=== SQLite -> PostgreSQL migration ===")
    print(f"Source: {sqlite_url}")
    print(f"Target: {mask_database_url(postgres_url)}")

    source_engine = create_engine(
        sqlite_url,
        connect_args={"check_same_thread": False},
    )
    target_engine = create_engine(postgres_url, pool_pre_ping=True)

    if args.dry_run:
        print_dry_run(source_engine)
        return

    print("\nCreating schema in PostgreSQL (if needed)...")
    create_postgres_schema(target_engine)

    if not args.no_truncate:
        print("Clearing target tables...")
        truncate_postgres(target_engine)

    print("\nCopying data...")
    copied_total = 0
    for table_name in TABLES_IN_ORDER:
        copied_total += copy_table(source_engine, target_engine, table_name)

    print("\nResetting PostgreSQL ID sequences...")
    reset_sequences(target_engine)

    print(f"\nDone. Copied {copied_total} rows.")


if __name__ == "__main__":
    main()
