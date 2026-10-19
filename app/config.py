from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BID_", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./data/development.db"
    storage_path: Path = Path("data/blobs")
    redis_url: str = "redis://localhost:6379/0"
    max_upload_bytes: int = 50 * 1024 * 1024
    max_pdf_pages: int = 300
    lease_seconds: int = 120
    job_max_attempts: int = 3
    dispatch_stale_seconds: int = 120
    parser_profile: str = "pdfplumber-probe-v1"
    demo_enabled: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
