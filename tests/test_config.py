"""Guardrails: the test config must be loaded, the local stack healthy, coverage honest.

The first test fails if the runtime environment (e.g. VSCode injecting `.env` via
`python.envFile`) overrides the `.env.test` values. pydantic-settings gives
environment variables priority over the `env_file`, so a `SUPABASE_API_URL` coming
from `.env` would mask the one in `.env.test`.

The second fails when the stack is *degraded* rather than down: a wedged Docker
proxy keeps accepting TCP while multiplying every round-trip (~×5 on the whole
suite). Better one loud failure here than a whole suite that is merely slow.

The third holds the one bug none of the others can see, because it breaks nothing — it
only lies. See its docstring.
"""

import tomllib
from pathlib import Path

import pytest

from apps.shared.settings.env import get_technical_settings
from scripts.doctor import CHECKS, WARN_SECONDS, timed

COV_FLAGS = ("--cov", "--no-cov")


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


def test_pytest_addopts_drive_no_coverage_plugin():
    """Coverage is started by `coverage run -m pytest`, never by pytest-cov's flags.

    pytest loads `-p tests.plugin` in `consider_preparse`, *before* it calls
    `pytest_load_initial_conftests` — which is where pytest-cov starts measuring. Since
    tests/plugin.py pulls in `apps.main` through its `pytest_plugins`, every module body in
    `apps/` would execute untraced and be reported as missed: 3452 statements, every
    `domain/models.py` at 0%, the whole figure off by 44 points. Nothing fails, nothing
    flakes — the number is simply wrong, which is why it needs a test of its own.
    """
    config = tomllib.loads(Path("pyproject.toml").read_text())
    addopts = config["tool"]["pytest"]["ini_options"]["addopts"]

    offenders = [opt for opt in addopts.split() if opt.startswith(COV_FLAGS)]

    assert offenders == []
