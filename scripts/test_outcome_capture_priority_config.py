"""Settings wiring for OUTCOME_CAPTURE_DI_WINNER_PRIORITY (Stage 1.23C.1A)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import Settings
from app.services.delayed_outcome_capture_config import (
    outcome_capture_budget_from_env,
    parse_outcome_capture_di_winner_priority_value,
)


def test_parse_missing_or_empty_is_disabled() -> None:
    assert parse_outcome_capture_di_winner_priority_value(None) is False
    assert parse_outcome_capture_di_winner_priority_value("") is False
    assert parse_outcome_capture_di_winner_priority_value("   ") is False


def test_parse_truthy_and_falsy_tokens() -> None:
    assert parse_outcome_capture_di_winner_priority_value("1") is True
    assert parse_outcome_capture_di_winner_priority_value("0") is False
    assert parse_outcome_capture_di_winner_priority_value("true") is True
    assert parse_outcome_capture_di_winner_priority_value("off") is False


def test_parse_malformed_raises() -> None:
    with pytest.raises(ValueError, match="OUTCOME_CAPTURE_DI_WINNER_PRIORITY"):
        parse_outcome_capture_di_winner_priority_value("maybe")


def _write_env(tmp_path: Path, *lines: str) -> Path:
    env_path = tmp_path / ".env"
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_path


def test_dotenv_enabled_without_shell_override(tmp_path, monkeypatch) -> None:
    _write_env(tmp_path, "OUTCOME_CAPTURE_DI_WINNER_PRIORITY=1")
    monkeypatch.delenv("OUTCOME_CAPTURE_DI_WINNER_PRIORITY", raising=False)
    monkeypatch.chdir(tmp_path)
    budget = outcome_capture_budget_from_env()
    assert budget.di_winner_priority_enabled is True


def test_dotenv_disabled_without_shell_override(tmp_path, monkeypatch) -> None:
    _write_env(tmp_path, "OUTCOME_CAPTURE_DI_WINNER_PRIORITY=0")
    monkeypatch.delenv("OUTCOME_CAPTURE_DI_WINNER_PRIORITY", raising=False)
    monkeypatch.chdir(tmp_path)
    budget = outcome_capture_budget_from_env()
    assert budget.di_winner_priority_enabled is False


def test_process_env_overrides_dotenv_enable(tmp_path, monkeypatch) -> None:
    _write_env(tmp_path, "OUTCOME_CAPTURE_DI_WINNER_PRIORITY=0")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OUTCOME_CAPTURE_DI_WINNER_PRIORITY", "1")
    budget = outcome_capture_budget_from_env()
    assert budget.di_winner_priority_enabled is True


def test_process_env_overrides_dotenv_disable(tmp_path, monkeypatch) -> None:
    _write_env(tmp_path, "OUTCOME_CAPTURE_DI_WINNER_PRIORITY=1")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OUTCOME_CAPTURE_DI_WINNER_PRIORITY", "0")
    budget = outcome_capture_budget_from_env()
    assert budget.di_winner_priority_enabled is False


def test_missing_key_defaults_off(tmp_path, monkeypatch) -> None:
    _write_env(tmp_path, "APP_NAME=Test")
    monkeypatch.delenv("OUTCOME_CAPTURE_DI_WINNER_PRIORITY", raising=False)
    monkeypatch.chdir(tmp_path)
    budget = outcome_capture_budget_from_env()
    assert budget.di_winner_priority_enabled is False


def test_malformed_in_dotenv_raises(tmp_path, monkeypatch) -> None:
    _write_env(tmp_path, "OUTCOME_CAPTURE_DI_WINNER_PRIORITY=maybe")
    monkeypatch.delenv("OUTCOME_CAPTURE_DI_WINNER_PRIORITY", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValidationError):
        outcome_capture_budget_from_env()


def test_worker_and_cli_resolve_identical_budget(tmp_path, monkeypatch) -> None:
    _write_env(tmp_path, "OUTCOME_CAPTURE_DI_WINNER_PRIORITY=1")
    monkeypatch.delenv("OUTCOME_CAPTURE_DI_WINNER_PRIORITY", raising=False)
    monkeypatch.chdir(tmp_path)
    worker_budget = outcome_capture_budget_from_env()
    cli_budget = outcome_capture_budget_from_env()
    assert worker_budget == cli_budget
    assert cli_budget.di_winner_priority_enabled is True


def test_settings_matches_budget_helper(tmp_path, monkeypatch) -> None:
    _write_env(tmp_path, "OUTCOME_CAPTURE_DI_WINNER_PRIORITY=1")
    monkeypatch.delenv("OUTCOME_CAPTURE_DI_WINNER_PRIORITY", raising=False)
    monkeypatch.chdir(tmp_path)
    settings = Settings()
    budget = outcome_capture_budget_from_env()
    assert settings.outcome_capture_di_winner_priority_enabled == budget.di_winner_priority_enabled
