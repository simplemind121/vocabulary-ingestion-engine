from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VIE_", extra="ignore")

    ocr_engine: str = "none"
    ocr_min_confidence: float = 0.85
    api_key: SecretStr | None = None
    redis_url: str | None = None
    storage_backend: str = "local"
    storage_root: Path = Path("data")
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_bucket: str = "vie-artifacts"
    s3_region: str = "us-east-1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
