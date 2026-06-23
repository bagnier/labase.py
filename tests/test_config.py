"""Guardrail: ensure the test config is actually loaded.

This test fails if the runtime environment (e.g. VSCode injecting `.env` via
`python.envFile`) overrides the `.env.test` values. pydantic-settings gives
environment variables priority over the `env_file`, so a `SUPABASE_URL` coming
from `.env` would mask the one in `.env.test`.
"""

from app.shared.config import get_technical_settings


def test_test_settings_are_loaded():
    settings = get_technical_settings()
    # .env.test points to local Supabase; .env points to host.docker.internal.
    assert settings.supabase_url == "http://localhost:54321", (
        f"test config not loaded: supabase_url={settings.supabase_url!r} "
        "(the environment is likely overriding .env.test — check python.envFile)"
    )
    assert "docker" not in settings.supabase_url
