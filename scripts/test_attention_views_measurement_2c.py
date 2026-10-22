"""Fix 2C — views_measurement_status mapping."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.attention_views_measurement import views_measurement_status  # noqa: E402


def test_winner_snapshot_paths() -> None:
    assert views_measurement_status(in_winner_snapshot=True, views=100, has_snapshot=True) == "from_winner_snapshot"
    assert views_measurement_status(in_winner_snapshot=True, views=0, has_snapshot=True) == "zero_in_winner_snapshot"
    assert (
        views_measurement_status(in_winner_snapshot=True, views=None, has_snapshot=True)
        == "unknown_in_winner_snapshot"
    )


def test_non_winner_snapshot_paths() -> None:
    assert views_measurement_status(in_winner_snapshot=False, views=50, has_snapshot=True) == "from_snapshot"
    assert views_measurement_status(in_winner_snapshot=False, views=0, has_snapshot=True) == "zero_in_snapshot"
    assert views_measurement_status(in_winner_snapshot=False, views=None, has_snapshot=True) == "unknown_in_snapshot"
    assert views_measurement_status(in_winner_snapshot=False, views=None, has_snapshot=False) == "missing_snapshot"


if __name__ == "__main__":
    test_winner_snapshot_paths()
    test_non_winner_snapshot_paths()
    print("ok")
