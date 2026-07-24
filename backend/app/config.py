from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application config, loaded from environment / .env.

    Secrets (notably NIMBLE_API_KEY) are read here and nowhere else. The raw
    key value is never logged or serialized — see `nimble_api_key` usage.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_env: str = "local"
    log_level: str = "INFO"

    # Nimble v2
    nimble_api_key: str = ""
    nimble_base_url: str = "https://sdk.nimbleway.com/v2"
    nimble_country: str = "US"
    nimble_driver: str = "auto"

    # Infra
    database_url: str = "postgresql+asyncpg://crate:crate@localhost:5432/crate"
    redis_url: str = "redis://localhost:6379/0"

    # Scraper rate limiting (stay well under Nimble's ~83 QPS ceiling)
    scraper_max_qps: float = 2.0
    scraper_max_concurrency: int = 4

    # Seed
    bandcamp_fan_url: str = ""

    @property
    def nimble_configured(self) -> bool:
        return bool(self.nimble_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
