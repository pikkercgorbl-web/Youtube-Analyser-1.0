"""Discovery-worker keyword expansion toggle (Stage 5 — default off)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class KeywordExpansionRuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    keyword_expansion_after_discovery: bool = Field(
        default=False,
        validation_alias="KEYWORD_EXPANSION_AFTER_DISCOVERY",
    )


keyword_expansion_runtime_settings = KeywordExpansionRuntimeSettings()
