"""Production configuration checks, run by ``make preflight`` (``scripts/preflight.py``) as a
deploy gate and by :func:`enforce_at_boot`, which refuses a production boot on a blocking error.
"""

import structlog

from apps.shared.settings.env import TechnicalSettings, get_technical_settings

log = structlog.get_logger(__name__)

# Hosts that must never appear in a production database URL.
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "host.docker.internal")

# Supabase's own secret key shapes: the current `sb_secret_…` format, or a legacy key,
# always a JWT and so starting on its base64 `{"alg"` header — the preflight checks the
# shape, not which role the JWT carries.
_SUPABASE_SECRET_KEY_PREFIXES = ("sb_secret_", "eyJ")


class PreflightError(RuntimeError):
    """Raised at boot when a production configuration fails a blocking check."""


def check_production(settings: TechnicalSettings) -> tuple[list[str], list[str]]:
    """``(errors, findings)``: errors fail the gate and the boot, findings do not."""
    errors: list[str] = []
    findings: list[str] = []

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
    if not any(
        settings.supabase_secret_key.startswith(prefix)
        and len(settings.supabase_secret_key) > len(prefix)
        for prefix in _SUPABASE_SECRET_KEY_PREFIXES
    ):
        errors.append(
            "SUPABASE_SECRET_KEY looks unset or malformed — expected `sb_secret_…` or a "
            "legacy JWT."
        )

    if not settings.is_production:
        findings.append(
            "ENVIRONMENT is not 'production' — the boot-time preflight gate stays inactive."
        )
    if settings.app_version == "dev":
        findings.append(
            "APP_VERSION is 'dev' — set the git SHA so error-tracking regression detection works."
        )
    if settings.log_debug:
        findings.append(
            "LOG_DEBUG is true — logs render as human-readable console text instead of the "
            "JSON an aggregator can parse."
        )
    if not settings.supabase_database_admin_url:
        findings.append(
            "SUPABASE_DATABASE_ADMIN_URL is empty — event handlers and console queries need it."
        )

    return errors, findings


def enforce_at_boot(settings: TechnicalSettings | None = None) -> None:
    """Raise :class:`PreflightError` on a blocking error, in production only."""
    settings = settings or get_technical_settings()
    if not settings.is_production:
        return
    errors, findings = check_production(settings)
    for detail in findings:
        # A surprise, not something absorbed or refused.
        # (AGENTS: a line says what no other record says)
        log.info("preflight.finding", detail=detail)
    if errors:
        # The details go in the exception the process dies on: it is what the operator reads,
        # and the capture seam ignores a ``log.error`` without one.
        raise PreflightError(
            f"production preflight failed with {len(errors)} blocking error(s); "
            f"refusing to boot: {'; '.join(errors)}"
        )
