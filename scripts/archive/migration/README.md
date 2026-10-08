# One-time migration tools (archived)

Not part of normal Radar launch. Used when copying hosted Postgres (legacy Supabase) into local Docker.

| Script | Purpose |
|--------|---------|
| `supabase_local_restore_check.py` | Inventory + trial restore to local Docker |
| `restore_check_readonly_audit.py` | Read-only schema/data compare: remote source vs `youtube_radar_restore_check` |

Run manually only when migrating. Day-to-day ops: `docs/LOCAL_RADAR_LAPTOP.md`, `docs/OPERATIONS_LAUNCH.md`.

Remote `DATABASE_URL` backups (if any): `backups/migration_archive/database_url_remote.env` (gitignored under `backups/`).
