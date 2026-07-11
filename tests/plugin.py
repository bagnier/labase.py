"""Global pytest entry point: clock bootstrap, the ``--driver`` option and the
``pytest_plugins`` registration of the BDD steps and e2e driver fixtures.

Registered via ``-p tests.plugin`` in pyproject so its options and the plugins it
pulls in are available to every test under ``app/`` and ``tests/`` — which a
directory-scoped conftest.py could not provide. Keeping it as an explicit plugin
lets the project root stay free of a conftest.py. The driver and per-test
isolation fixtures live in ``tests.e2e.plugin`` (pulled in below).
"""

import os

os.environ.setdefault("ENV_FILE", ".env.test")

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import tests.e2e.clock as test_clock
from apps.shared.config import get_technical_settings
from tests.e2e import cleanup

# Clear feature-switch overrides before pytest imports the nested plugins below — which pull in
# the drivers and therefore ``apps.main``, whose disabled set is read at import time. A leftover
# ``enabled = false`` (e.g. from manual dev testing on the shared DB) would otherwise unmount an
# app for the whole run.
cleanup.reset_app_switches()

pytest_plugins = [
    "tests.e2e.plugin",
    "tests.e2e.steps_common",
    "apps.auth.tests.e2e.steps",
    "apps.api_keys.tests.e2e.steps",
    "apps.issues.tests.e2e.steps",
    "apps.metrics.tests.e2e.steps",
    "apps.logs.tests.e2e.steps",
    "apps.console.tests.e2e.steps",
    "apps.profile.tests.e2e.steps",
    "apps.todo.tests.e2e.steps",
    "apps.learning.tests.e2e.steps",
    "apps.files.tests.e2e.steps",
    "apps.pages.tests.e2e.steps",
    "apps.calendar.tests.e2e.steps",
    "apps.organizations.tests.e2e.steps",
]


def pytest_addoption(parser):
    parser.addoption("--driver", default="api", choices=["api", "browser"])


def pytest_runtest_setup(item):
    """A @web scenario only makes sense through a browser (rendered chrome, DOM
    placement); skip it on any non-browser driver so the functional suite stays
    surface-agnostic. pytest-bdd turns the Gherkin @web tag into this marker."""
    if item.get_closest_marker("web") and item.config.getoption("--driver") != "browser":
        pytest.skip("web-only scenario; runs under the browser driver")


@pytest.fixture
def clock():
    """The test clock for date-pinning steps — independent of the driver."""
    return test_clock


@pytest.fixture(autouse=True)
def reset_clock(monkeypatch):
    """Route apps.shared.clock.now onto the test clock, and unpin it after the test.

    Both drivers run the app in-process, so a plain monkeypatch reaches every
    runtime clock.now() call — including the in-thread browser server.
    """
    monkeypatch.setattr("apps.shared.clock.now", test_clock.now)
    yield
    test_clock.reset()


@pytest_asyncio.fixture()
async def db_session():
    """RLS-enforcing session (user role) for direct integration tests (no HTTP).

    Uses a throwaway engine wrapped in a single transaction rolled back at teardown:
    set_rls_context sets a transaction-local role + claims, so the rollback discards
    them and nothing needs disposing back to a shared pool.
    """
    settings = get_technical_settings()
    connect_args = {
        "server_settings": {"search_path": f"{settings.supabase_database_schema},public"}
    }
    engine = create_async_engine(settings.supabase_database_user_url, connect_args=connect_args)
    try:
        async with engine.connect() as conn:
            await conn.begin()
            async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                yield session
            await conn.rollback()
    finally:
        await engine.dispose()
