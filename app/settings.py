from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VIE_", extra="ignore")

    ocr_engine: str = "none"
    ocr_languages: str = "eng+chi_sim"
    ocr_min_confidence: float = 0.85
    # Extra readers voted against the primary engine, e.g. "rapidocr-v5,vision".
    ocr_secondary_readers: str = ""
    vision_ocr_url: str | None = None
    # Readings produced elsewhere (e.g. macOS Vision on a Mac), laid out as
    # <root>/<document sha256>/<reader>/p0001.json.
    ocr_readings_root: Path | None = None
    # Pages read at the same time; each worker loads its own engines.
    ocr_page_workers: int = 1
    # Vision model that arbitrates lines the OCR readers disagree on. Any
    # endpoint speaking the OpenAI Chat Completions protocol works.
    arbiter_api_key: SecretStr | None = None
    arbiter_model: str = ""
    arbiter_base_url: str = "https://api.openai.com/v1"
    arbiter_batch_size: int = 20
    # Dictionaries used for pronunciations OCR cannot read, in priority order:
    # "ecdict:/path/ecdict.csv,britfone:/path/britfone.csv,ipadict:/path/en_UK.txt".
    pronunciation_dictionaries: str = ""
    api_key: SecretStr | None = None
    max_upload_bytes: int = Field(default=512 * 1024 * 1024, ge=1)
    max_pdf_pages: int = Field(default=5000, ge=1)
    max_render_pixels_per_page: int = Field(default=40_000_000, ge=1)
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
