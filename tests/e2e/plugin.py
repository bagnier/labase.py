"""E2e driver fixtures: the session-scoped driver and per-test isolation.

Registered via ``pytest_plugins`` from ``tests.plugin`` so these reach every BDD
scenario under ``app/`` while keeping the driver concerns grouped under e2e.
The ``--driver`` option itself stays in ``tests.plugin`` (the ``-p`` entry point),
since ``pytest_addoption`` is only honoured for plugins loaded at startup.
"""

import asyncio

import pytest

from tests.e2e import cleanup
from tests.e2e.drivers.api import ApiDriver
from tests.e2e.drivers.browser import BrowserDriver


@pytest.fixture(scope="session")
def driver(request) -> ApiDriver | BrowserDriver:
    name = request.config.getoption("--driver")
    d = BrowserDriver() if name == "browser" else ApiDriver()
    d.start()

    def finalize() -> None:
        d.stop()
        asyncio.run(cleanup.purge_leftover_test_data())

    request.addfinalizer(finalize)
    return d


@pytest.fixture(autouse=True)
def db_rollback(driver: ApiDriver | BrowserDriver):
    """Each test/scenario runs inside its driver's isolation boundary.

    ApiDriver wraps the test in a rolled-back transaction shared by all sessions;
    BrowserDriver truncates app tables after the fact. Each driver owns its own
    strategy via setup_test/teardown_test (see tests/e2e/drivers/).
    """
    driver.setup_test()
    yield
    driver.teardown_test()
