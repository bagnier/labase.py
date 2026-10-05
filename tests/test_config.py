"""Guardrails: the test config is the one loaded, the stack is not degraded, coverage is
measured."""

import os
import tomllib
from pathlib import Path

import pytest
from dotenv import dotenv_values

from apps.shared.settings.env import get_technical_settings
from scripts.doctor import CHECKS, WARN_SECONDS, timed

COV_FLAGS = ("--cov", "--no-cov")


def test_test_settings_are_loaded():
    settings = get_technical_settings()
    # An environment variable (VSCode's `python.envFile` loading `.env`, which points to
    # host.docker.internal) would override `.env.test`.
    env_file_url = dotenv_values(os.environ["ENV_FILE"])["SUPABASE_API_URL"]
    assert settings.supabase_api_url == env_file_url, (
        f"test config not loaded: supabase_api_url={settings.supabase_api_url!r} "
        "(the environment is likely overriding .env.test — check python.envFile)"
    )
    assert "docker" not in settings.supabase_api_url


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "check"), CHECKS, ids=[name for name, _ in CHECKS])
async def test_local_stack_is_responsive(name, check):
    """A wedged Docker proxy still accepts TCP but slows every round trip ×5. ×4 headroom over
    doctor's threshold spares a busy laptop."""
    budget = WARN_SECONDS * 4
    elapsed = await timed(check)
    assert elapsed < budget, (
        f"{name} answered in {elapsed:.2f}s (> {budget:.1f}s) — the local stack is "
        "degraded; run `make doctor` and consider restarting Docker/OrbStack"
    )


def test_pytest_addopts_drive_no_coverage_plugin():
    """Coverage starts with `coverage run`, never pytest-cov: `-p tests.plugin` imports
    `apps.main` before pytest-cov starts, and every module body would count as missed."""
    config = tomllib.loads(Path("pyproject.toml").read_text())
    addopts = config["tool"]["pytest"]["ini_options"]["addopts"]

    offenders = [opt for opt in addopts.split() if opt.startswith(COV_FLAGS)]

    assert offenders == []
