from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://dlp:dlp@localhost:5433/mini_dlp"
    MAX_SCAN_TEXT_CHARS: int = 1_000_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
