#!/usr/bin/env python3
"""Read-only schema and data audit: Supabase vs youtube_radar_restore_check."""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, inspect, text

import app.models.orm  # noqa: F401
import app.models.radar_v01  # noqa: F401
from app.core.config import normalize_database_url
from app.models.db import Base
from migrate import load_dotenv

RESTORE_DB = "youtube_radar_restore_check"
MISSING_EXT = ("uuid-ossp", "pgcrypto", "supabase_vault", "pg_stat_statements")
EXT_FN_PATTERNS = (
    "uuid_generate",
    "gen_random_uuid",
    "crypt(",
    "digest(",
    "encrypt(",
    "decrypt(",
    "vault.",
    "extensions.uuid",
)


def source_engine():
    load_dotenv(PROJECT_ROOT / ".env")
    url = normalize_database_url(os.environ.get("DATABASE_URL", "").strip())
    return create_engine(url, pool_pre_ping=True)


def local_engine():
    load_dotenv(PROJECT_ROOT / ".env.docker")
    from urllib.parse import quote

    user = os.environ["RADAR_LOCAL_DB_USER"].strip()
    pw = quote(os.environ["RADAR_LOCAL_DB_PASSWORD"].strip(), safe="")
    url = f"postgresql://{user}:{pw}@127.0.0.1:5433/{RESTORE_DB}"
    return create_engine(url, pool_pre_ping=True)


def fetch_set(conn, sql: str) -> set[str]:
    return {row[0] for row in conn.execute(text(sql))}


def schema_snapshot(conn) -> dict:
    tables = fetch_set(
        conn,
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
        ORDER BY 1;
        """,
    )
    views = fetch_set(
        conn,
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'v'
        ORDER BY 1;
        """,
    )
    sequences = fetch_set(
        conn,
        """
        SELECT sequencename FROM pg_sequences WHERE schemaname = 'public' ORDER BY 1;
        """,
    )
    functions = {
        f"{r[0]}({r[1]})"
        for r in conn.execute(
            text(
                """
                SELECT p.proname, pg_get_function_identity_arguments(p.oid)
                FROM pg_proc p
                JOIN pg_namespace n ON p.pronamespace = n.oid
                WHERE n.nspname = 'public'
                  AND p.prokind IN ('f', 'p', 'w')
                ORDER BY 1, 2;
                """
            )
        )
    }
    triggers = {
        f"{r[0]} ON {r[1]}"
        for r in conn.execute(
            text(
                """
                SELECT t.tgname, c.relname
                FROM pg_trigger t
                JOIN pg_class c ON t.tgrelid = c.oid
                JOIN pg_namespace n ON c.relnamespace = n.oid
                WHERE n.nspname = 'public' AND NOT t.tgisinternal
                ORDER BY 2, 1;
                """
            )
        )
    }
    types = fetch_set(
        conn,
        """
        SELECT t.typname
        FROM pg_type t
        JOIN pg_namespace n ON t.typnamespace = n.oid
        WHERE n.nspname = 'public'
          AND t.typtype IN ('e', 'c', 'd')
          AND NOT EXISTS (
            SELECT 1 FROM pg_depend d
            WHERE d.objid = t.oid AND d.deptype = 'i'
          )
        ORDER BY 1;
        """,
    )
    constraints = {
        r[0]
        for r in conn.execute(
            text(
                """
                SELECT con.conname || ' [' || con.contype::text || '] ON ' || rel.relname
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                JOIN pg_namespace n ON n.oid = rel.relnamespace
                WHERE n.nspname = 'public'
                ORDER BY 1;
                """
            )
        )
    }
    columns = {}
    for r in conn.execute(
        text(
            """
            SELECT table_name, column_name, column_default,
                   is_generated, generation_expression, data_type, udt_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position;
            """
        )
    ):
        key = (r[0], r[1])
        columns[key] = {
            "default": r[2],
            "is_generated": r[3],
            "generation_expression": r[4],
            "data_type": r[5],
            "udt_name": r[6],
        }
    return {
        "tables": tables,
        "views": views,
        "sequences": sequences,
        "functions": functions,
        "triggers": triggers,
        "types": types,
        "constraints": constraints,
        "columns": columns,
    }


def extension_public_deps(conn) -> dict:
    rows = conn.execute(
        text(
            """
            SELECT e.extname, c.relname
            FROM pg_depend d
            JOIN pg_extension e ON d.refobjid = e.oid
            JOIN pg_class c ON d.objid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = 'public'
              AND e.extname = ANY(:exts)
            ORDER BY 1, 2;
            """
        ),
        {"exts": list(MISSING_EXT)},
    ).fetchall()

    col_refs = []
    for r in conn.execute(
        text(
            """
            SELECT table_name, column_name, column_default, generation_expression
            FROM information_schema.columns
            WHERE table_schema = 'public';
            """
        )
    ):
        blob = " ".join(x or "" for x in r[2:]).lower()
        for pat in EXT_FN_PATTERNS:
            if pat.lower() in blob:
                col_refs.append(
                    {"table": r[0], "column": r[1], "pattern": pat, "expr": (r[2] or r[3] or "")[:200]}
                )
    # Functions in public that belong to extensions
    fn_ext = [
        {"ext": r[0], "function": r[1]}
        for r in conn.execute(
            text(
                """
                SELECT e.extname, p.oid::regprocedure::text
                FROM pg_depend d
                JOIN pg_extension e ON d.refobjid = e.oid
                JOIN pg_proc p ON d.objid = p.oid
                JOIN pg_namespace n ON p.pronamespace = n.oid
                WHERE n.nspname = 'public'
                  AND e.extname = ANY(:exts)
                  AND d.deptype = 'e';
                """
            ),
            {"exts": list(MISSING_EXT)},
        )
    ]
    return {"depend_rows": [{"ext": a, "obj": b} for a, b in rows], "column_refs": col_refs, "functions": fn_ext}


def table_counts(conn, tables: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in tables:
        # identifier quoting for safety
        q = f'"{t}"' if t.isidentifier() else t
        n = conn.execute(text(f"SELECT count(*) FROM public.{q}")).scalar_one()
        out[t] = int(n)
    return out


def fk_orphan_checks(conn) -> list[dict]:
    fks = conn.execute(
        text(
            """
            SELECT con.conname,
                   src.relname AS src_table,
                   array_agg(sa.attname ORDER BY u.ord) AS src_cols,
                   tgt.relname AS tgt_table,
                   array_agg(ta.attname ORDER BY u.ord) AS tgt_cols
            FROM pg_constraint con
            JOIN pg_class src ON src.oid = con.conrelid
            JOIN pg_class tgt ON tgt.oid = con.confrelid
            JOIN pg_namespace n ON n.oid = src.relnamespace
            JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS u(attnum, ord) ON true
            JOIN pg_attribute sa ON sa.attrelid = src.oid AND sa.attnum = u.attnum
            JOIN pg_attribute ta ON ta.attrelid = tgt.oid AND ta.attnum = con.confkey[u.ord - 1]
            WHERE n.nspname = 'public' AND con.contype = 'f'
            GROUP BY con.conname, src.relname, tgt.relname
            ORDER BY src.relname, con.conname;
            """
        )
    ).fetchall()
    orphans: list[dict] = []
    for fk in fks:
        name, src, src_cols, tgt, tgt_cols = fk
        src_cols = list(src_cols)
        tgt_cols = list(tgt_cols)
        join = " AND ".join(f's."{sc}" = t."{tc}"' for sc, tc in zip(src_cols, tgt_cols))
        nulls = " OR ".join(f's."{sc}" IS NULL' for sc in src_cols)
        sql = f"""
            SELECT count(*) FROM public."{src}" s
            WHERE NOT ({nulls})
              AND NOT EXISTS (
                SELECT 1 FROM public."{tgt}" t WHERE {join}
              )
        """
        cnt = conn.execute(text(sql)).scalar_one()
        if int(cnt) > 0:
            orphans.append({"fk": name, "src": src, "tgt": tgt, "orphan_rows": int(cnt)})
    return orphans


def orm_schema_expectations(local_eng) -> dict:
    insp = inspect(local_eng)
    expected_tables = set(Base.metadata.tables.keys())
    db_tables = set(insp.get_table_names(schema="public"))
    missing_tables = expected_tables - db_tables
    extra_tables = db_tables - expected_tables
    column_gaps: list[dict] = []
    for tname in sorted(expected_tables & db_tables):
        model_cols = {c.name for c in Base.metadata.tables[tname].columns}
        db_cols = {c["name"] for c in insp.get_columns(tname, schema="public")}
        miss = sorted(model_cols - db_cols)
        extra = sorted(db_cols - model_cols)
        if miss or extra:
            column_gaps.append({"table": tname, "missing_in_db": miss, "extra_in_db": extra})
    return {
        "expected_table_count": len(expected_tables),
        "missing_tables": sorted(missing_tables),
        "extra_tables": sorted(extra_tables),
        "column_gaps": column_gaps,
    }


def local_select_checks(conn) -> dict:
    version = conn.execute(text("SELECT version()")).scalar_one().split(",")[0]
    seqs = [
        {"name": r[0], "last_value": r[1], "start_value": r[2], "increment_by": r[3]}
        for r in conn.execute(
            text(
                """
                SELECT sequencename, last_value, start_value, increment_by
                FROM pg_sequences
                WHERE schemaname = 'public'
                ORDER BY sequencename;
                """
            )
        )
    ]
    pk_count = conn.execute(
        text(
            """
            SELECT count(*) FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = rel.relnamespace
            WHERE n.nspname = 'public' AND con.contype = 'p';
            """
        )
    ).scalar_one()
    fk_count = conn.execute(
        text(
            """
            SELECT count(*) FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = rel.relnamespace
            WHERE n.nspname = 'public' AND con.contype = 'f';
            """
        )
    ).scalar_one()
    return {
        "version": version,
        "public_table_count": len(
            fetch_set(
                conn,
                "SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relkind='r';",
            )
        ),
        "primary_keys": int(pk_count),
        "foreign_keys": int(fk_count),
        "sequences": seqs,
    }


def diff_sets(a: set, b: set) -> dict:
    return {"only_source": sorted(a - b), "only_target": sorted(b - a), "common": len(a & b)}


def diff_columns(src: dict, tgt: dict) -> list[dict]:
    diffs = []
    all_keys = set(src) | set(tgt)
    for key in sorted(all_keys):
        s, t = src.get(key), tgt.get(key)
        if s != t:
            diffs.append({"table": key[0], "column": key[1], "source": s, "target": t})
    return diffs


def main() -> None:
    started = datetime.now(timezone.utc).isoformat()
    src_eng = source_engine()
    loc_eng = local_engine()

    with src_eng.connect() as src, loc_eng.connect() as loc:
        src_snap = schema_snapshot(src)
        tgt_snap = schema_snapshot(loc)
        src_ext = extension_public_deps(src)
        tgt_ext = extension_public_deps(loc)
        tables = sorted(src_snap["tables"] | tgt_snap["tables"])
        src_counts = table_counts(src, tables)
        tgt_counts = table_counts(loc, tables)
        count_diffs = [
            {"table": t, "source": src_counts[t], "target": tgt_counts.get(t), "delta": tgt_counts.get(t, 0) - src_counts[t]}
            for t in tables
            if src_counts.get(t) != tgt_counts.get(t)
        ]
        fk_src = fk_orphan_checks(src)
        fk_tgt = fk_orphan_checks(loc)

    orm = orm_schema_expectations(loc_eng)
    with loc_eng.connect() as loc:
        local_checks = local_select_checks(loc)

    with loc_eng.connect() as loc:
        local_ext_names = fetch_set(loc, "SELECT extname FROM pg_extension ORDER BY 1;")

    report = {
        "audit_started_utc": started,
        "schema": {
            "tables": diff_sets(src_snap["tables"], tgt_snap["tables"]),
            "views": diff_sets(src_snap["views"], tgt_snap["views"]),
            "sequences": diff_sets(src_snap["sequences"], tgt_snap["sequences"]),
            "functions": diff_sets(src_snap["functions"], tgt_snap["functions"]),
            "triggers": diff_sets(src_snap["triggers"], tgt_snap["triggers"]),
            "types": diff_sets(src_snap["types"], tgt_snap["types"]),
            "constraints": diff_sets(src_snap["constraints"], tgt_snap["constraints"]),
            "column_diff_count": len(diff_columns(src_snap["columns"], tgt_snap["columns"])),
            "column_diffs": diff_columns(src_snap["columns"], tgt_snap["columns"]),
        },
        "extension_deps_source": src_ext,
        "extension_deps_target": tgt_ext,
        "local_extensions": sorted(local_ext_names),
        "row_counts": {"source": src_counts, "target": tgt_counts, "diffs": count_diffs},
        "fk_orphans_source": fk_src,
        "fk_orphans_target": fk_tgt,
        "orm_alignment": orm,
        "local_select_checks": local_checks,
    }

    out_path = PROJECT_ROOT / "backups" / "restore_check_audit.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"written": str(out_path), "summary_keys": list(report.keys())}))


if __name__ == "__main__":
    main()
