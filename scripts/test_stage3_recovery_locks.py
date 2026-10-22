"""Stage 3: worker + publish lock recovery checks (reuses existing test functions)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load_module(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    discovery = _load_module("test_discovery_worker")
    monitoring = _load_module("test_monitoring_worker")
    checks = [
        discovery.test_singleton_lock_blocks_second_worker,
        discovery.test_stale_lock_recovery,
        discovery.test_lock_released_on_shutdown,
        monitoring.test_singleton_lock_blocks_second_worker,
        monitoring.test_stale_lock_recovery,
        monitoring.test_lock_released_on_shutdown,
        monitoring.test_dry_run_no_network_or_persistence,
    ]
    for fn in checks:
        fn()
        print(f"OK {fn.__name__}")
    print("OK stage3 recovery locks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
