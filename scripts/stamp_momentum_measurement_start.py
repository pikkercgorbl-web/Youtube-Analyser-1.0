#!/usr/bin/env python3
"""Record UTC start of continuous worker observation (run once after workers restart)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv


def main() -> int:
    load_dotenv(ROOT / ".env")
    from app.services.metrics import utc_now

    now = utc_now()
    marker = ROOT / "artifacts" / "momentum_measurement_start.json"
    marker.parent.mkdir(exist_ok=True)
    payload = {
        "measurement_start_utc": now.isoformat(),
        "note": "Set when discovery/monitoring workers are running continuously after published_at fix",
    }
    marker.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(f"Also export: MOMENTUM_MEASUREMENT_START_UTC={now.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
