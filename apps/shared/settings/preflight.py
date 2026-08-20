"""Production configuration safety checks.

Two entry points share one rule set:

* ``make preflight`` (``scripts/preflight.py``) — a deploy gate: point it at the
  production env file and it exits non-zero on any blocking error.
* :func:`enforce_at_boot` — called from the composition root; when
  ``ENVIRONMENT=production`` a bad config raises and the process refuses to boot
  instead of serving traffic with development defaults.
"""

import structlog

from apps.shared.settings.env import TechnicalSettings, get_technical_settings

log = structlog.get_logger(__name__)

# Hosts that must never appear in a production database URL.
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "host.docker.internal")


class PreflightError(RuntimeError):
    """Raised at boot when a production configuration fails a blocking check."""


def check_production(settings: TechnicalSettings) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)`` for a would-be production configuration.

    Errors are blocking (they fail the gate and refuse boot); warnings are
    surfaced but non-blocking.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not settings.cookies_secure:
        errors.append(
            "COOKIES_SECURE is false — session cookies would ride plain HTTP and be dropped."
        )
    if "*" in settings.cors_origins:
        errors.append("CORS_ORIGINS contains '*' — declare explicit allowed origins.")
    for name, url in (
        ("SUPABASE_DATABASE_USER_URL", settings.supabase_database_user_url),
        ("SUPABASE_DATABASE_ADMIN_URL", settings.supabase_database_admin_url),
    ):
        if any(host in url for host in _LOCAL_HOSTS):
            errors.append(f"{name} points at a local host — not a production database.")
    if len(settings.supabase_secret_key) < 40:
        errors.append("SUPABASE_SECRET_KEY looks unset or too short.")

    if not settings.is_production:
        warnings.append(
            "ENVIRONMENT is not 'production' — the boot-time preflight gate stays inactive."
        )
    if settings.app_version == "dev":
        warnings.append(
            "APP_VERSION is 'dev' — set the git SHA so error-tracking regression detection works."
        )
    if settings.log_debug:
        warnings.append(
            "LOG_DEBUG is true — logs render as human-readable console text instead of the "
            "JSON an aggregator can parse."
        )
    if not settings.supabase_database_admin_url:
        warnings.append(
            "SUPABASE_DATABASE_ADMIN_URL is empty — event handlers and console queries need it."
        )

    return errors, warnings


def enforce_at_boot(settings: TechnicalSettings | None = None) -> None:
    """Fail fast at startup when running in production with a blocking misconfig."""
    settings = settings or get_technical_settings()
    if not settings.is_production:
        return
    errors, warnings = check_production(settings)
    for detail in warnings:
        log.warning("preflight.warning", detail=detail)
    if errors:
        # The details ride the exception rather than lines of their own. The process is about to
        # die on it, so its message is what an operator reads — and a ``log.error`` carrying no
        # exception is exactly the spelling the capture seam skips, which made the one report
        # that mattered the one nothing could act on. A boot that succeeds says nothing at all.
        raise PreflightError(
            f"production preflight failed with {len(errors)} blocking error(s); "
            f"refusing to boot: {'; '.join(errors)}"
        )
