from collections.abc import Generator

import pytest

from tests.bdd.drivers.api import ApiDriver
from tests.bdd.drivers.browser import BrowserDriver


def pytest_addoption(parser):
    parser.addoption("--driver", default="api", choices=["api", "browser"])


@pytest.fixture(scope="session")
def driver(request) -> Generator[ApiDriver | BrowserDriver, None, None]:
    name = request.config.getoption("--driver")
    d = BrowserDriver() if name == "browser" else ApiDriver()
    d.start()
    yield d
    d.stop()
