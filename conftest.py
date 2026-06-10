import pytest

from tests.e2e.drivers.api import ApiDriver
from tests.e2e.drivers.browser import BrowserDriver

pytest_plugins = [
    "app.auth.tests.steps",
    "app.dashboard.tests.steps",
    "app.todo.tests.steps",
    "app.files.tests.steps",
]


def pytest_addoption(parser):
    parser.addoption("--driver", default="api", choices=["api", "browser"])


@pytest.fixture(scope="session")
def driver(request) -> ApiDriver | BrowserDriver:
    name = request.config.getoption("--driver")
    d = BrowserDriver() if name == "browser" else ApiDriver()
    d.start()
    request.addfinalizer(d.stop)
    return d


@pytest.fixture(scope="session")
def browser_driver(request) -> BrowserDriver:
    d = BrowserDriver()
    d.start()
    request.addfinalizer(d.stop)
    return d
