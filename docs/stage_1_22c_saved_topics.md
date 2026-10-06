# Stage 1.22C — Saved Topics / Watchlist

**Status:** done (2026-10-06)

## Scope

- Persist watchlist entries by `family_key` (not raw `pattern_key`).
- Immutable **frozen snapshot** built server-side from the current Attention snapshot at first save.
- Append-only **observations** keyed by `(saved_topic_id, attention_run_id)` without FK to `attention_runs`.
- After each Attention snapshot replace (`persist_attention_result`), append observations for non-archived topics in the **same transaction** (caller commits; helper only add/flush).
- REST under `/api/saved-topics`; UI `/saved-topics`, `/saved-topics/[id]`.

## Data model

| Table | Notes |
|-------|--------|
| `saved_topics` | Unique `family_key`; status, notes, tags, frozen JSON, archive timestamp |
| `saved_topic_observations` | Historical provenance `attention_run_id` (string, no FK) |

User status: `WATCHING` | `WANT_TO_TEST` | `TESTING` | `DROPPED`.

When a family is missing from a new snapshot, observation records `present_in_snapshot: false` and the fixed absence message — **no zero-filled counts**.

## Tests

- `scripts/test_saved_topics_1_22c.py` (isolated SQLite, not production DB).
- `scripts/test_saved_topics_1_22c_postgres_regression.py` (dedicated Postgres test DB only).

## Verification

- Backend regression: 9 tests passed.
- Frontend: `npm run build` passed.
- Local Postgres: backup `backups/pre_saved_topics_20261006.dump` (docker `pg_dump`); startup migration `ensure_saved_topics_tables`.

## Limitations

- Single-user: one row per `family_key`.
- Live UI examples on detail use frozen breakout video evidence; full video hydrate is via Opportunities family page.
- Observation append runs on every snapshot persist (including manual `persist_attention_result`).
