#!/usr/bin/env python3
"""
ARCHIVED: one-time migration only (see scripts/archive/migration/README.md).

Read-only remote Postgres inventory + trial restore to local Docker Postgres.
Does not modify .env or DATABASE_URL. Prints no secrets.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text

from app.core.config import normalize_database_url
from migrate import load_dotenv, mask_database_url

# Supabase-managed schemas (exclude from app table comparison).
SUPABASE_SYSTEM_SCHEMAS = frozenset(
    {
        "auth",
        "extensions",
        "graphql",
        "graphql_public",
        "pgbouncer",
        "realtime",
        "storage",
        "supabase_functions",
        "supabase_migrations",
        "vault",
        "_realtime",
    }
)

APP_SCHEMAS = ("public",)

LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 5433
RESTORE_DB = "youtube_radar_restore_check"
BASE_DB = "youtube_radar"


def load_source_url() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url or url.startswith("sqlite"):
        raise SystemExit("ERROR: DATABASE_URL missing or points to SQLite in .env")
    return normalize_database_url(url)


def load_local_url(base_db: str) -> str:
    load_dotenv(PROJECT_ROOT / ".env.docker")
    user = os.environ.get("RADAR_LOCAL_DB_USER", "").strip()
    password = os.environ.get("RADAR_LOCAL_DB_PASSWORD", "").strip()
    if not user or not password:
        raise SystemExit("ERROR: RADAR_LOCAL_DB_USER/PASSWORD missing in .env.docker")
    # URL-encode minimal: password may contain special chars
    from urllib.parse import quote

    pw = quote(password, safe="")
    return f"postgresql://{user}:{pw}@{LOCAL_HOST}:{LOCAL_PORT}/{base_db}"


def parse_db_name(url: str) -> str:
    path = urlparse(url).path.lstrip("/")
    return path.split("?")[0] or "(unknown)"


def user_tables_sql() -> str:
    schemas = ", ".join(f"'{s}'" for s in APP_SCHEMAS)
    return f"""
    SELECT n.nspname AS schema_name,
           c.relname AS table_name,
           GREATEST(c.reltuples::bigint, 0) AS approx_rows
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind = 'r'
      AND n.nspname IN ({schemas})
    ORDER BY n.nspname, c.relname;
    """


def fetch_inventory(engine) -> dict:
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version()")).scalar_one()
        pg_version = conn.execute(text("SHOW server_version")).scalar_one()
        db_name = conn.execute(text("SELECT current_database()")).scalar_one()
        extensions = conn.execute(
            text(
                """
                SELECT extname, extversion
                FROM pg_extension
                ORDER BY extname;
                """
            )
        ).fetchall()
        tables = conn.execute(text(user_tables_sql())).fetchall()
    return {
        "database": db_name,
        "version_line": version.split(",")[0] if version else "",
        "server_version": pg_version,
        "extensions": [(r[0], r[1]) for r in extensions],
        "tables": [(r[0], r[1], int(r[2])) for r in tables],
    }


def sequences_sql() -> str:
    schemas = ", ".join(f"'{s}'" for s in APP_SCHEMAS)
    return f"""
    SELECT sequence_schema, sequence_name, last_value
    FROM information_schema.sequences s
    LEFT JOIN LATERAL (
        SELECT last_value FROM pg_sequences ps
        WHERE ps.schemaname = s.sequence_schema AND ps.sequencename = s.sequence_name
    ) lv ON true
    WHERE sequence_schema IN ({schemas})
    ORDER BY 1, 2;
    """


def fetch_sequences(engine) -> list[tuple]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT schemaname, sequencename, last_value
                FROM pg_sequences
                WHERE schemaname IN ('public')
                ORDER BY schemaname, sequencename;
                """
            )
        ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def db_size_bytes(engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text("SELECT pg_database_size(current_database())")).scalar_one())


def run_pg_dump(source_url: str, dump_path: Path) -> None:
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    schema_args = []
    for s in APP_SCHEMAS:
        schema_args.extend(["-n", s])
    cmd = [
        "pg_dump",
        "-Fc",
        "--no-owner",
        "--no-acl",
        *schema_args,
        "-f",
        str(dump_path),
        source_url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"pg_dump failed (exit {proc.returncode}):\n{err[:4000]}")


def run_createdb(local_postgres_url: str, db_name: str) -> None:
    engine = create_engine(local_postgres_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"),
            {"n": db_name},
        ).scalar_one_or_none()
        if exists:
            raise SystemExit(
                f"ERROR: database {db_name} already exists; refusing to overwrite.",
            )
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))


def run_pg_restore(dump_path: Path, target_url: str) -> None:
    cmd = [
        "pg_restore",
        "--no-owner",
        "--no-acl",
        "--exit-on-error",
        "-d",
        target_url,
        str(dump_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"pg_restore failed (exit {proc.returncode}):\n{err[:8000]}")


def compare_tables(
    source: list[tuple], target: list[tuple]
) -> dict:
    src_map = {(s, t): n for s, t, n in source}
    tgt_map = {(s, t): n for s, t, n in target}
    all_keys = sorted(set(src_map) | set(tgt_map))
    mismatches = []
    for key in all_keys:
        sn = src_map.get(key)
        tn = tgt_map.get(key)
        if sn is None or tn is None:
            mismatches.append({"table": key, "source_rows": sn, "target_rows": tn})
        elif sn != tn:
            mismatches.append({"table": key, "source_rows": sn, "target_rows": tn})
    return {
        "source_table_count": len(src_map),
        "target_table_count": len(tgt_map),
        "missing_on_target": [k for k in src_map if k not in tgt_map],
        "extra_on_target": [k for k in tgt_map if k not in src_map],
        "row_estimate_mismatches": mismatches,
    }


def compose_exec_db(args: list[str]) -> subprocess.CompletedProcess:
    cmd = [
        "docker",
        "compose",
        "--env-file",
        str(PROJECT_ROOT / ".env.docker"),
        "exec",
        "-T",
        "db",
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)


def docker_pg_dump_remote(source_url: str, container_dump: str) -> subprocess.CompletedProcess:
    backups = PROJECT_ROOT / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{backups}:/backups",
        "postgres:17",
        "pg_dump",
        "-Fc",
        "--no-owner",
        "--no-acl",
        "-n",
        "public",
        "-f",
        container_dump,
        source_url,
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "report"
    source_url = load_source_url()
    safe_meta = {
        "database": parse_db_name(source_url),
        "host_hint": urlparse(source_url).hostname or "",
        "port": urlparse(source_url).port,
        "masked_url": mask_database_url(source_url),
    }

    if action == "inventory":
        eng = create_engine(source_url, pool_pre_ping=True)
        inv = fetch_inventory(eng)
        print(json.dumps({"connection_meta": safe_meta, "inventory": inv}, ensure_ascii=False))
        return

    if action == "local-check":
        base_url = load_local_url(BASE_DB)
        inv = fetch_inventory(create_engine(base_url, pool_pre_ping=True))
        restore_exists = False
        postgres_url = load_local_url("postgres")
        with create_engine(postgres_url, isolation_level="AUTOCOMMIT").connect() as conn:
            restore_exists = (
                conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :n"),
                    {"n": RESTORE_DB},
                ).scalar_one_or_none()
                is not None
            )
        print(
            json.dumps(
                {
                    "base_db": inv,
                    "restore_db_exists": restore_exists,
                },
                ensure_ascii=False,
            )
        )
        return

    if action == "dump":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dump_name = f"supabase_public_{stamp}.dump"
        dump_path = PROJECT_ROOT / "backups" / dump_name
        proc = docker_pg_dump_remote(source_url, f"/backups/{dump_name}")
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            # Strip credentials if driver echoes URI
            err = re.sub(r"://[^@\s]+@", "://***@", err)
            print(err[:8000])
            sys.exit(proc.returncode)
        size = dump_path.stat().st_size
        print(json.dumps({"dump_path": str(dump_path), "size_bytes": size}, ensure_ascii=False))
        return

    if action == "create-restore-db":
        load_dotenv(PROJECT_ROOT / ".env.docker")
        user = os.environ.get("RADAR_LOCAL_DB_USER", "radar")
        proc = compose_exec_db(
            [
                "psql",
                "-U",
                user,
                "-d",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
                "-tAc",
                f"SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname = '{RESTORE_DB}');",
            ]
        )
        if proc.returncode == 0 and (proc.stdout or "").strip() == "t":
            raise SystemExit(f"ERROR: database {RESTORE_DB} already exists")
        proc = compose_exec_db(
            [
                "psql",
                "-U",
                user,
                "-d",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                f'CREATE DATABASE "{RESTORE_DB}"',
            ]
        )
        if proc.returncode != 0:
            print((proc.stderr or proc.stdout)[:4000])
            sys.exit(proc.returncode)
        print(json.dumps({"created": RESTORE_DB}))
        return

    if action == "restore":
        dump_path = Path(sys.argv[2])
        if not dump_path.is_file():
            raise SystemExit(f"Missing dump: {dump_path}")
        container_path = f"/tmp/{dump_path.name}"
        cp = subprocess.run(
            [
                "docker",
                "cp",
                str(dump_path),
                f"youtube-radar-local-db-1:{container_path}",
            ],
            capture_output=True,
            text=True,
        )
        if cp.returncode != 0:
            print(cp.stderr[:4000])
            sys.exit(cp.returncode)
        load_dotenv(PROJECT_ROOT / ".env.docker")
        user = os.environ.get("RADAR_LOCAL_DB_USER", "radar")
        list_proc = compose_exec_db(["pg_restore", "-l", container_path])
        if list_proc.returncode != 0:
            print((list_proc.stderr or list_proc.stdout)[:4000])
            sys.exit(list_proc.returncode)
        filtered_lines: list[str] = []
        for line in (list_proc.stdout or "").splitlines():
            stripped = line.lstrip("; ").strip()
            if (
                " SCHEMA - public " in line
                and stripped.startswith("SCHEMA")
                and "COMMENT" not in line
                and "ACL" not in line
            ):
                filtered_lines.append(f"; {line.lstrip('; ')}")
            else:
                filtered_lines.append(line)
        filtered_path = "/tmp/restore.filtered.toc"
        write_toc = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                str(PROJECT_ROOT / ".env.docker"),
                "exec",
                "-T",
                "db",
                "bash",
                "-lc",
                f"cat > {filtered_path}",
            ],
            input="\n".join(filtered_lines) + "\n",
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        if write_toc.returncode != 0:
            print((write_toc.stderr or write_toc.stdout)[:4000])
            sys.exit(write_toc.returncode)
        proc = compose_exec_db(
            [
                "pg_restore",
                "--no-owner",
                "--no-acl",
                "--exit-on-error",
                "-U",
                user,
                "-d",
                RESTORE_DB,
                "-L",
                filtered_path,
                container_path,
            ]
        )
        if proc.returncode != 0:
            print((proc.stderr or proc.stdout)[:8000])
            sys.exit(proc.returncode)
        print(json.dumps({"restored": RESTORE_DB}))
        return

    if action == "compare-live-stats":
        src_eng = create_engine(source_url, pool_pre_ping=True)
        tgt_eng = create_engine(load_local_url(RESTORE_DB), pool_pre_ping=True)
        stat_sql = text(
            """
            SELECT relname, n_live_tup::bigint
            FROM pg_stat_user_tables
            WHERE schemaname = 'public'
            ORDER BY relname;
            """
        )
        with src_eng.connect() as conn:
            src_map = {r[0]: int(r[1]) for r in conn.execute(stat_sql)}
        with tgt_eng.connect() as conn:
            tgt_map = {r[0]: int(r[1]) for r in conn.execute(stat_sql)}
        diffs = []
        for name in sorted(set(src_map) | set(tgt_map)):
            s, t = src_map.get(name, 0), tgt_map.get(name, 0)
            if s != t:
                diffs.append({"table": name, "source_live": s, "target_live": t, "delta": t - s})
        print(
            json.dumps(
                {
                    "source_total_live": sum(src_map.values()),
                    "target_total_live": sum(tgt_map.values()),
                    "diffs": diffs,
                },
                ensure_ascii=False,
            )
        )
        return

    if action == "compare":
        dump_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
        src_eng = create_engine(source_url, pool_pre_ping=True)
        tgt_eng = create_engine(load_local_url(RESTORE_DB), pool_pre_ping=True)
        src_inv = fetch_inventory(src_eng)
        tgt_inv = fetch_inventory(tgt_eng)
        cmp = compare_tables(src_inv["tables"], tgt_inv["tables"])
        seq_src = fetch_sequences(src_eng)
        seq_tgt = fetch_sequences(tgt_eng)
        print(
            json.dumps(
                {
                    "source_extensions": src_inv["extensions"],
                    "target_extensions": tgt_inv["extensions"],
                    "comparison": cmp,
                    "sequences_source_count": len(seq_src),
                    "sequences_target_count": len(seq_tgt),
                    "sequence_mismatches": [
                        {"seq": s, "source": a, "target": b}
                        for s, a, b in zip(
                            [x[1] for x in seq_src],
                            [x[2] for x in seq_src],
                            [x[2] for x in seq_tgt],
                        )
                        if a != b
                    ][:50],
                    "target_db_size_bytes": db_size_bytes(tgt_eng),
                    "dump_size_bytes": dump_path.stat().st_size if dump_path and dump_path.is_file() else None,
                },
                ensure_ascii=False,
            )
        )
        return

    raise SystemExit(f"Unknown action: {action}")


if __name__ == "__main__":
    main()
