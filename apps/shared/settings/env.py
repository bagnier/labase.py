"""Technical settings: read once from the environment (``.env``) and cached; a change takes a
restart, as a deployment-owned value should."""

import os
from functools import lru_cache

from pydantic import AliasChoices, Field, PositiveInt, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The interval of a per-process background loop, in seconds — ``0`` disables that loop.
type PollSeconds = float


class TechnicalSettings(BaseSettings):
    # populate_by_name: else `environment`, which has an alias, could not be set by its own name.
    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", ".env"), extra="ignore", populate_by_name=True
    )

    supabase_api_url: str
    supabase_publishable_key: str
    supabase_secret_key: str
    supabase_storage_url: str = ""
    # Browser-facing Studio base URL; empty means this deployment has no Studio (links hidden).
    supabase_studio_url: str = ""
    supabase_storage_bucket: str = "org-files"
    supabase_database_user_url: str
    supabase_database_admin_url: str = ""
    supabase_database_schema: str = "public"
    # "production" turns on the boot-time preflight gate.
    environment: str = Field(
        default="development",
        validation_alias=AliasChoices("ENVIRONMENT", "LABASE_ENV"),
    )
    log_debug: bool = False
    # Per-day files for the log batches Postgres refuses. Production points it at a real volume.
    # (AGENTS: the log sink traces the machinery off the request's path)
    firehose_dir: str = ".cache/firehose"
    cookies_secure: bool = True
    rate_limit_enabled: bool = True
    # Past this wait on the counter store (connect, pool, query), the request goes through
    # unlimited and the dependency verdict opens an issue.
    rate_limit_store_timeout_seconds: float = 2.0
    # Use the left-most X-Forwarded-For entry as the client IP. Only behind a proxy we control:
    # otherwise any caller can spoof its IP, evading rate limits and poisoning logs.
    trust_forwarded_for: bool = False
    # No cross-origin access until listed. "*" works but turns credentials off (see cors_config).
    cors_origins: list[str] = []
    settings_refresh_seconds: PollSeconds = 30  # re-read, for cross-instance freshness
    task_worker_interval_seconds: PollSeconds = 1.0
    metrics_flush_seconds: PollSeconds = 60
    # For un-fingerprinted static files; `?v=…` ones are immutable. 0 always revalidates (dev).
    static_cache_seconds: int = 3600
    # Drain of the log queue into ``log_lines``. At 0 the drain stops and new lines are dropped.
    firehose_flush_seconds: PollSeconds = 1.0
    # Past this wait on a lock (a concurrent TRUNCATE), the batch goes to the day files. Above
    # zero: to Postgres a ``lock_timeout`` of 0 means no timeout at all.
    log_drain_lock_timeout_seconds: float = Field(default=2.0, ge=0.001)
    # How long a capture is retried, still owed to some tracker, before it is parked rather than
    # requeued — mirroring ``apps/shared/queue.py``'s ``TaskWorker`` (retry, then park), so a
    # value no tracker can ever store stops spamming a fresh traceback for the life of the
    # process. Generous on purpose: short enough that a permanently unstorable value does not
    # haunt the queue forever, long enough that an ordinary outage (minutes, not seconds) still
    # gets its capture delivered once the tracker recovers.
    capture_retry_seconds: PositiveInt = 3600
    # Git SHA in Docker; an issue seen again on a newer version regresses.
    app_version: str = "dev"
    # Defaults target the local mail catcher (Mailpit). 127.0.0.1, not localhost, keeps DNS out
    # of local connections.
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 54325
    smtp_sender: str = "labase <noreply@labase.local>"
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False
    # Mailpit's HTTP API, read by the e2e mailbox and `make doctor`.
    mailpit_url: str = "http://127.0.0.1:54324"
    # Page length of `scripts/backup_storage.py`'s Storage listing. Positive: at 0 the paging
    # never advances.
    backup_storage_page_size: PositiveInt = 1000

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
    # pydantic-settings fills the required fields from the environment; the generated __init__
    # still lists them as parameters. A TYPE_CHECKING `__init__(**values)` would clear this line
    # but stop checking the explicit kwargs in test_preflight.
    return TechnicalSettings()  # pyright: ignore[reportCallIssue]
