import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=os.getenv("ENV_FILE", ".env"), extra="ignore")

    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    database_url: str
    database_url_service: str = ""
    db_schema: str = "public"
    log_debug: bool = False
    cookies_secure: bool = True
    rate_limit_enabled: bool = True
    cors_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # ty: ignore[missing-argument]
