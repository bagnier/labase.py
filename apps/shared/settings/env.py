"""Process-wide technical settings, read once from the environment (``.env``).

Infrastructure knobs — DB URLs, SMTP, cache TTLs — cached for the process lifetime. Changing
one takes a restart, which is what a deployment-owned value should cost. Its sibling
:mod:`apps.shared.settings.live` holds the other lifetime: admin-tunable, per-app, reloaded live.
"""

import os
from functools import lru_cache

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The interval of a per-process background loop, in seconds — ``0`` disables that loop.
type PollSeconds = float


class TechnicalSettings(BaseSettings):
    # populate_by_name: `environment` carries a validation_alias, which would otherwise make it
    # the one field settable only by its alias and not by its own name.
    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", ".env"), extra="ignore", populate_by_name=True
    )

    supabase_api_url: str
    supabase_publishable_key: str
    supabase_secret_key: str
    supabase_storage_url: str = ""
    supabase_storage_bucket: str = "org-files"
    supabase_database_user_url: str
    supabase_database_admin_url: str = ""
    supabase_database_schema: str = "public"
    # "production" activates the boot-time preflight gate (apps/shared/settings/preflight.py).
    environment: str = Field(
        default="development",
        validation_alias=AliasChoices("ENVIRONMENT", "LABASE_ENV"),
    )
    log_debug: bool = False
    # Where a batch goes when Postgres refuses it: lines are rendered to stdout and appended to
    # ``log_lines``, and only a failing write falls back to per-day JSON files here — a database
    # outage is exactly when an operator still wants the log. Production points this at a real
    # log volume. The env var keeps its FIREHOSE_ name, which a deploy already sets.
    firehose_dir: str = ".firehose"
    cookies_secure: bool = True
    rate_limit_enabled: bool = True
    # Behind a reverse proxy/LB, the socket peer is the proxy, so the real client sits in
    # X-Forwarded-For. Off by default: trusting that header when nothing upstream strips it
    # lets any caller spoof their IP (evading rate limits, poisoning logs). Turn on ONLY when a
    # proxy we control sets it — then the left-most entry (the edge-observed client) is used.
    trust_forwarded_for: bool = False
    # Closed by default: no cross-origin access until CORS_ORIGINS lists the exact front-end
    # origins that need it. "*" is honoured but forces credentials off (see cors_config).
    cors_origins: list[str] = []
    settings_refresh_seconds: PollSeconds = 30  # re-read, for cross-instance freshness
    task_worker_interval_seconds: PollSeconds = 1.0  # the task worker's claim poll
    metrics_flush_seconds: PollSeconds = 60  # flush of the request accumulator
    # Browser cache TTL for un-fingerprinted static files; fingerprinted ones (?v=…) are served
    # immutable regardless. 0 → always revalidate (dev).
    static_cache_seconds: int = 3600
    # At 0 the background writer stops, and the runtime log path drops lines rather than block.
    firehose_flush_seconds: PollSeconds = 1.0  # drain of the log queue into ``log_lines``
    # Deployed version (git SHA in Docker); drives error-tracking regression detection.
    app_version: str = "dev"
    # These defaults target the local Supabase mail catcher (Mailpit); prod sets SMTP_* to any
    # provider, and sending stays best-effort (see apps/shared/email.py). 127.0.0.1 rather than
    # localhost keeps DNS out of every local connection.
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 54325
    smtp_sender: str = "labase <noreply@labase.local>"
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False

    @model_validator(mode="after")
    def _default_storage_url(self) -> TechnicalSettings:
        if not self.supabase_storage_url:
            self.supabase_storage_url = self.supabase_api_url
        return self

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"


@lru_cache
def get_technical_settings() -> TechnicalSettings:
    # The one construction that passes nothing: pydantic-settings fills the required fields from
    # the environment, while the generated __init__ advertises them as parameters. Kept as a
    # suppression rather than a TYPE_CHECKING `__init__(**values)`, which would clear this line at
    # the cost of checking test_preflight's nine explicit kwargs.
    return TechnicalSettings()  # pyright: ignore[reportCallIssue]
