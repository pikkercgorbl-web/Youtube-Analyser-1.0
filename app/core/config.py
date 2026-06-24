import os

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_SQLITE_FALLBACK = "sqlite:///./database.db"


def normalize_database_url(url: str | None) -> str:
    """Resolve DATABASE_URL with SQLite fallback and postgres:// → postgresql:// fix."""
    resolved = (url or "").strip() or _SQLITE_FALLBACK
    if resolved.startswith("postgres://"):
        resolved = resolved.replace("postgres://", "postgresql://", 1)
    return resolved


DATABASE_URL = normalize_database_url(os.environ.get("DATABASE_URL"))


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "YouTube Analytics"
    debug: bool = False
    database_url: str = Field(default=DATABASE_URL, validation_alias="DATABASE_URL")
    youtube_api_keys_raw: str = Field(default="", validation_alias="YOUTUBE_API_KEYS")
    explosive_radar_interval_seconds: int = Field(
        default=300,
        ge=60,
        validation_alias="EXPLOSIVE_RADAR_INTERVAL_SECONDS",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: object) -> str:
        if value is None or (isinstance(value, str) and not value.strip()):
            return normalize_database_url(os.environ.get("DATABASE_URL"))
        return normalize_database_url(str(value))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def youtube_api_keys(self) -> list[str]:
        if not self.youtube_api_keys_raw.strip():
            return []
        return [item.strip() for item in self.youtube_api_keys_raw.split(",") if item.strip()]


settings = Settings()
