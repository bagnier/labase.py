"""E2e driver fixtures: the session-scoped driver and per-test isolation.

Registered via ``pytest_plugins`` from ``tests.plugin`` so these reach every BDD
scenario under ``app/`` while keeping the driver concerns grouped under e2e.
The ``--driver`` option itself stays in ``tests.plugin`` (the ``-p`` entry point),
since ``pytest_addoption`` is only honoured for plugins loaded at startup.
"""

import asyncio
from collections.abc import Iterator

import pytest

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
    """Each test/scenario runs inside its driver's isolation boundary.

    ApiDriver wraps the test in a rolled-back transaction shared by all sessions;
    BrowserDriver truncates app tables after the fact. Each driver owns its own
    strategy via setup_test/teardown_test (see tests/e2e/drivers/).

    reset_session() then clears the (session-scoped) driver's per-scenario state —
    client/cookies, browser context, acting-as user — so every scenario starts
    clean without each entry @given having to remember to do it.
    """
    driver.setup_test()
    driver.reset_session()
    yield
    driver.teardown_test()
