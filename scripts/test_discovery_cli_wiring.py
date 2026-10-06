"""Fast tests for discovery cycle CLI wiring (Stage 1.20C.1). No network / remote DB."""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.services.discovery_cycle import DiscoveryCycleOutcome, DiscoveryCycleSummary
from app.services.metrics import utc_now


def _load_cli_module():
    path = ROOT / "scripts" / "run_discovery_cycle.py"
    spec = importlib.util.spec_from_file_location("run_discovery_cycle_cli", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sqlite_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return factory


def test_cli_dry_run_and_batch_size_wiring() -> None:
    cli = _load_cli_module()
    captured: dict[str, object] = {}

    def fake_run_cycle(session, youtube_client, config, dry_run=False):
        captured["dry_run"] = dry_run
        captured["batch_size"] = config.keyword_batch_size
        captured["has_session"] = session is not None
        captured["has_client"] = youtube_client is not None
        now = utc_now()
        return DiscoveryCycleOutcome(
            summary=DiscoveryCycleSummary(
                run_id="cli_wiring_test",
                started_at=now,
                finished_at=now,
                cycle_status="dry_run" if dry_run else "ok",
                selected_keyword_count=0,
            ),
        )

    factory = _sqlite_session_factory()
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(
            ["--dry-run", "--batch-size", "2"],
            session_factory=factory,
            youtube_client_factory=lambda: object(),
            run_cycle=fake_run_cycle,
        )
    out = buf.getvalue()
    assert code == 0
    assert captured["dry_run"] is True
    assert captured["batch_size"] == 2
    assert "cli_wiring_test" in out
    assert "run_id" in out


def test_cli_failed_cycle_exit_code() -> None:
    cli = _load_cli_module()
    factory = _sqlite_session_factory()
    now = utc_now()

    def failed_cycle(*_a, **_k):
        return DiscoveryCycleOutcome(
            summary=DiscoveryCycleSummary(
                run_id="cli_fail",
                started_at=now,
                finished_at=now,
                cycle_status="failed",
            ),
        )

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(
            [],
            session_factory=factory,
            youtube_client_factory=lambda: object(),
            run_cycle=failed_cycle,
        )
    assert code == 1
    assert "cli_fail" in buf.getvalue()


def main() -> None:
    tests = [test_cli_dry_run_and_batch_size_wiring, test_cli_failed_cycle_exit_code]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"OK {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    if failed:
        raise SystemExit(f"{failed} failed")
    print("All discovery CLI wiring tests passed.")


if __name__ == "__main__":
    main()
