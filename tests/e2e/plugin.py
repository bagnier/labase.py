"""The session-scoped driver and per-test isolation, registered from ``tests.plugin``, which keeps
``--driver``: ``pytest_addoption`` works only in startup plugins.
"""

import asyncio
from collections.abc import Iterator

import pytest

from apps.shared.settings.live import restore_settings, settings_snapshot
from tests.e2e import cleanup
from tests.e2e.drivers.api import ApiDriver
from tests.e2e.drivers.browser import BrowserDriver


@pytest.fixture(scope="session")
def driver(request) -> Iterator[ApiDriver | BrowserDriver]:
    name = request.config.getoption("--driver")
    d = BrowserDriver() if name == "browser" else ApiDriver()
    d.start()
    yield d
    d.stop()
    asyncio.run(cleanup.purge_leftover_test_data())


@pytest.fixture(autouse=True)
def db_rollback(driver: ApiDriver | BrowserDriver):
    """Each test inside its driver's isolation (rollback or truncation), then
    ``reset_session()``. In-memory settings handles, which neither undoes, are snapshotted and
    restored."""
    settings = settings_snapshot()
    driver.setup_test()
    driver.reset_session()
    yield
    driver.teardown_test()
    restore_settings(settings)
