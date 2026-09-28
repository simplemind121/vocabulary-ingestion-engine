from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VIE_", extra="ignore")

    ocr_engine: str = "none"
    ocr_min_confidence: float = 0.85


@lru_cache
def get_settings() -> Settings:
    return Settings()
