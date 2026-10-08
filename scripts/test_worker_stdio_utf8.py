#!/usr/bin/env python3
"""Smoke: UTF-8 logging/print on Windows worker stdio (no DB/API)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.utils.worker_stdio import configure_worker_stdio_utf8

SAMPLE = "Radar worker UTF-8: кириллица ™ — 日本語"


def main() -> int:
    configure_worker_stdio_utf8()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log = logging.getLogger("test_worker_stdio_utf8")
    print(SAMPLE)
    log.warning(SAMPLE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
