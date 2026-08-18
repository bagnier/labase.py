"""Guardrails: the test config must be loaded, and the local stack must be healthy.

The first test fails if the runtime environment (e.g. VSCode injecting `.env` via
`python.envFile`) overrides the `.env.test` values. pydantic-settings gives
environment variables priority over the `env_file`, so a `SUPABASE_API_URL` coming
from `.env` would mask the one in `.env.test`.

The second fails when the stack is *degraded* rather than down: a wedged Docker
proxy keeps accepting TCP while multiplying every round-trip (~×5 on the whole
suite). Better one loud failure here than 341 silently slow tests.
"""

import pytest

from apps.shared.config import get_technical_settings
from scripts.doctor import CHECKS, WARN_SECONDS, timed


def test_test_settings_are_loaded():
    settings = get_technical_settings()
    # .env.test points to local Supabase; .env points to host.docker.internal.
    assert settings.supabase_api_url == "http://127.0.0.1:54321", (
        f"test config not loaded: supabase_api_url={settings.supabase_api_url!r} "
        "(the environment is likely overriding .env.test — check python.envFile)"
    )
    assert "docker" not in settings.supabase_api_url


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "check"), CHECKS, ids=[name for name, _ in CHECKS])
async def test_local_stack_is_responsive(name, check):
    """Generous ×4 headroom over doctor's warn threshold: catch the ×5 degradation, not a busy
    laptop."""
    budget = WARN_SECONDS * 4
    elapsed = await timed(check)
    assert elapsed < budget, (
        f"{name} answered in {elapsed:.2f}s (> {budget:.1f}s) — the local stack is "
        "degraded; run `make doctor` and consider restarting Docker/OrbStack"
    )
