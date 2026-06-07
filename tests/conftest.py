from collections.abc import Generator

import pytest

from tests.bdd.drivers.browser import BrowserDriver

pytest_plugins = ["tests.bdd.steps"]


@pytest.fixture(scope="session")
def browser_driver() -> Generator[BrowserDriver, None, None]:
    d = BrowserDriver()
    d.start()
    yield d
    d.stop()
