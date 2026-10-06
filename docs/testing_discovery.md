# Discovery testing boundaries

## Fast regression (deterministic)

SQLite, mocks, injected CLI dependencies. Safe on every change.

```powershell
python scripts/run_fast_regressions.py
```

Includes `test_operations_liveness.py` (worker activity vs lock age).

Individual slices:

```powershell
python scripts/test_discovery_worker.py
python scripts/test_discovery_cli_wiring.py
python scripts/test_discovery_cycle.py
```

These must **not** call live PostgreSQL, the public network, or InnerTube.

## Live discovery smoke (integration)

Uses real `SessionLocal`, `get_youtube_client()`, and `run_discovery_cycle` via the CLI.

Requires configured `DATABASE_URL`, network, and YouTube/InnerTube.

```powershell
python scripts/test_discovery_cli_live.py
```

Failures here usually indicate environment or integration issues, not a broken unit test.

## Why separate

`run_discovery_cycle.py --dry-run` still executes the real discovery stack when invoked as a subprocess. That is appropriate for manual/CI smoke tests but not for a fast regression gate (timeouts, remote DB latency, network flakiness).
