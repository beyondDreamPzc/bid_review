from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr
from typing import Literal


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
    parser_profile: str = "mineru-4.0.12-flash-auto-v1"
    mineru_python: str = "/opt/mineru/bin/python"
    mineru_timeout_seconds: int = Field(default=900,ge=10,le=3600)
    mineru_max_result_bytes: int = Field(default=50*1024*1024,ge=1024,le=200*1024*1024)
    demo_enabled: bool = False
    retrieval_enabled: bool = False
    milvus_url: str = "http://milvus:19530"
    milvus_token: SecretStr = SecretStr("")
    semantic_enabled: bool = False
    semantic_url: str = "http://semantic:8010"
    libreoffice_path: str = "/usr/bin/libreoffice"
    llm_enabled: bool = False
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    llm_output_mode: Literal["json_schema", "json_object"] = "json_schema"
    llm_token_parameter: Literal["max_completion_tokens", "max_tokens"] = "max_completion_tokens"
    llm_timeout_seconds: int = Field(default=45, ge=5, le=60)
    llm_max_output_tokens: int = Field(default=4096, ge=256, le=8192)
    llm_allow_insecure_http: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
