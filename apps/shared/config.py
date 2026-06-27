import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TechnicalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=os.getenv("ENV_FILE", ".env"), extra="ignore")

    supabase_api_url: str
    supabase_publishable_key: str
    supabase_secret_key: str
    supabase_storage_url: str = ""
    supabase_storage_bucket: str = "org-files"
    supabase_database_user_url: str
    supabase_database_admin_url: str = ""
    supabase_database_schema: str = "public"
    log_debug: bool = False
    cookies_secure: bool = True
    rate_limit_enabled: bool = True
    cors_origins: list[str] = ["*"]

    @model_validator(mode="after")
    def _default_storage_url(self) -> TechnicalSettings:
        if not self.supabase_storage_url:
            self.supabase_storage_url = self.supabase_api_url
        return self


@lru_cache
def get_technical_settings() -> TechnicalSettings:
    return TechnicalSettings()  # ty: ignore[missing-argument]
