from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://scar:scar@localhost:5432/scar"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "scar-assets"

    cache_long_ttl_seconds: int = 86400  # 24 h — closed/historical window
    cache_short_ttl_seconds: int = 60  # 60 s — open-ended or not-found
    presigned_url_expires_in: int = 3600  # 1 h


def get_settings() -> Settings:
    return Settings()
