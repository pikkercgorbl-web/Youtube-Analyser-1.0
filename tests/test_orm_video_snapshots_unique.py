"""Ensure video_snapshots is registered once on shared Base metadata (Stage 1.11 vs radar v0.1)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.models.orm  # noqa: F401
import app.models.radar_v01  # noqa: F401
from app.models.db import Base


def test_video_snapshots_table_registered_once() -> None:
    tables = [name for name in Base.metadata.tables if name == "video_snapshots"]
    assert tables == ["video_snapshots"]
    table = Base.metadata.tables["video_snapshots"]
    assert "captured_at" in table.c
    assert "recorded_at" not in table.c
    assert "baseline_source" not in table.c


def main() -> None:
    test_video_snapshots_table_registered_once()
    print("OK: video_snapshots metadata unique")


if __name__ == "__main__":
    main()
