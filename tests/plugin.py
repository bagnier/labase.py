"""Global pytest plugin: test isolation, the driver fixture and BDD step plugins.

Registered via ``-p tests.plugin`` in pyproject so its fixtures, options and the
autouse isolation are available to every test under ``app/`` and ``tests/`` —
which a directory-scoped conftest.py could not provide. Keeping it as an explicit
plugin lets the project root stay free of a conftest.py.
"""

import asyncio
import os

os.environ.setdefault("ENV_FILE", ".env.test")
# Mount the test-only clock endpoint so the browser driver can pin "today" in the
# app subprocess. Set before app import; inherited by the subprocess via os.environ.
os.environ.setdefault("ENABLE_TEST_CLOCK", "1")

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import tests.cleanup as cleanup
from app.shared.config import get_settings
from tests.e2e.drivers.api import ApiDriver
from tests.e2e.drivers.browser import BrowserDriver

pytest_plugins = [
    "app.auth.tests.steps",
    "app.console.tests.steps",
    "app.profile.tests.steps",
    "app.todo.tests.steps",
    "app.learning.tests.steps",
    "app.files.tests.steps",
    "app.organizations.tests.steps",
]


def pytest_addoption(parser):
    parser.addoption("--driver", default="api", choices=["api", "browser"])


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


@pytest_asyncio.fixture()
async def db_session():
    """RLS-enforcing session (user role) for direct integration tests (no HTTP).

    Uses a throwaway engine: set_rls_context does a session-level ``SET role``,
    so the connection must be disposed rather than returned to a shared pool.
    """
    settings = get_settings()
    connect_args = {"server_settings": {"search_path": f"{settings.db_schema},public"}}
    engine = create_async_engine(settings.database_url, connect_args=connect_args)
    try:
        async with engine.connect() as conn:
            await conn.begin()
            async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                yield session
            await conn.rollback()
    finally:
        await engine.dispose()


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
