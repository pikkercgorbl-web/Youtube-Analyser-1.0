from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "YouTube Analytics"
    debug: bool = False
    database_url: str = "sqlite:///./database.db"
    youtube_api_keys_raw: str = Field(default="", validation_alias="YOUTUBE_API_KEYS")
    explosive_radar_interval_seconds: int = Field(
        default=300,
        ge=60,
        validation_alias="EXPLOSIVE_RADAR_INTERVAL_SECONDS",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def youtube_api_keys(self) -> list[str]:
        if not self.youtube_api_keys_raw.strip():
            return []
        return [item.strip() for item in self.youtube_api_keys_raw.split(",") if item.strip()]


settings = Settings()
