import pytest

from apps.shared.settings.env import TechnicalSettings
from apps.shared.settings.preflight import PreflightError, check_production, enforce_at_boot

_REMOTE_DB = "postgresql+asyncpg://user@db.abcdefgh.supabase.co:6543/postgres"
_EXPLICIT_ORIGINS = ["https://app.example.com"]


def _settings(
    *,
    supabase_secret_key: str = "sb_secret_" + "x" * 32,
    supabase_database_user_url: str = _REMOTE_DB,
    supabase_database_admin_url: str = _REMOTE_DB,
    environment: str = "production",
    cookies_secure: bool = True,
    cors_origins: list[str] = _EXPLICIT_ORIGINS,
    log_debug: bool = False,
    app_version: str = "1a2b3c4",
) -> TechnicalSettings:
    """A production config that passes every check, minus the given overrides.

    Every field `check_production` reads is passed explicitly, so the ambient
    .env cannot leak into the result.
    """
    return TechnicalSettings(
        supabase_api_url="https://abcdefgh.supabase.co",
        supabase_publishable_key="sb_publishable_" + "x" * 32,
        supabase_secret_key=supabase_secret_key,
        supabase_database_user_url=supabase_database_user_url,
        supabase_database_admin_url=supabase_database_admin_url,
        environment=environment,
        cookies_secure=cookies_secure,
        cors_origins=cors_origins,
        log_debug=log_debug,
        app_version=app_version,
    )


def test_a_sound_production_config_raises_nothing():
    assert check_production(_settings()) == ([], [])


def test_insecure_cookies_block_the_deploy():
    errors, _ = check_production(_settings(cookies_secure=False))
    assert errors == [
        "COOKIES_SECURE is false — session cookies would ride plain HTTP and be dropped."
    ]


def test_wildcard_cors_blocks_the_deploy():
    errors, _ = check_production(_settings(cors_origins=["*"]))
    assert errors == ["CORS_ORIGINS contains '*' — declare explicit allowed origins."]


def test_a_local_user_database_blocks_the_deploy():
    errors, _ = check_production(
        _settings(supabase_database_user_url="postgresql+asyncpg://user@localhost:54322/postgres")
    )
    assert errors == [
        "SUPABASE_DATABASE_USER_URL points at a local host — not a production database."
    ]


def test_a_local_admin_database_blocks_the_deploy():
    errors, _ = check_production(
        _settings(
            supabase_database_admin_url="postgresql+asyncpg://postgres@127.0.0.1:54322/postgres"
        )
    )
    assert errors == [
        "SUPABASE_DATABASE_ADMIN_URL points at a local host — not a production database."
    ]


def test_a_short_secret_key_blocks_the_deploy():
    errors, _ = check_production(_settings(supabase_secret_key="too-short"))
    assert errors == ["SUPABASE_SECRET_KEY looks unset or too short."]


def test_a_non_production_environment_only_warns():
    errors, warnings = check_production(_settings(environment="staging"))
    assert (errors, warnings) == (
        [],
        ["ENVIRONMENT is not 'production' — the boot-time preflight gate stays inactive."],
    )


def test_an_unset_app_version_only_warns():
    _, warnings = check_production(_settings(app_version="dev"))
    assert warnings == [
        "APP_VERSION is 'dev' — set the git SHA so error-tracking regression detection works."
    ]


def test_console_rendering_only_warns():
    """``LOG_DEBUG`` no longer picks a level — with no ``debug`` tier there is none to pick. What
    it still decides is the renderer, and a production server rendering console text is one whose
    aggregator has nothing to parse. Warned, not blocked: the logs are readable either way."""
    _, warnings = check_production(_settings(log_debug=True))

    assert warnings == [
        (
            "LOG_DEBUG is true — logs render as human-readable console text instead of the "
            "JSON an aggregator can parse."
        )
    ]


def test_a_missing_admin_database_only_warns():
    _, warnings = check_production(_settings(supabase_database_admin_url=""))
    assert warnings == [
        "SUPABASE_DATABASE_ADMIN_URL is empty — event handlers and console queries need it."
    ]


def test_boot_refuses_a_production_config_with_a_blocking_error():
    with pytest.raises(PreflightError):
        enforce_at_boot(_settings(cookies_secure=False))


def test_boot_ignores_a_blocking_error_outside_production():
    assert enforce_at_boot(_settings(environment="development", cookies_secure=False)) is None
