"""Runtime log-level control: SettingsChanged re-points structlog and stdlib live."""

import logging

import pytest
import structlog

from apps.settings.contract.observability import OBSERVABILITY_APP, reload
from apps.settings.contract.settings import SettingsChanged
from apps.shared.observability.logging import apply_log_level, setup_logging


@pytest.fixture(autouse=True)
def restore_logging():
    yield
    setup_logging()  # back to the env-driven default level


@pytest.mark.asyncio
async def test_settings_change_applies_the_level_live():
    await reload(SettingsChanged(OBSERVABILITY_APP, {"log_level": "ERROR"}))
    assert logging.getLogger().level == logging.ERROR
    wrapper = structlog.get_config()["wrapper_class"]
    assert wrapper is structlog.make_filtering_bound_logger(logging.ERROR)


@pytest.mark.asyncio
async def test_another_apps_change_leaves_the_level_alone():
    apply_log_level("WARNING")
    await reload(SettingsChanged("todo", {"log_level": "ERROR"}))
    assert logging.getLogger().level == logging.WARNING


def test_invalid_level_is_ignored():
    apply_log_level("WARNING")
    apply_log_level("nonsense")
    assert logging.getLogger().level == logging.WARNING


def test_level_names_are_case_insensitive():
    apply_log_level("debug")
    assert logging.getLogger().level == logging.DEBUG
