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
from app.shared.config import get_settings

pytest_plugins = [
    "tests.e2e.plugin",
    "app.auth.tests.e2e.steps",
    "app.console.tests.e2e.steps",
    "app.profile.tests.e2e.steps",
    "app.todo.tests.e2e.steps",
    "app.learning.tests.e2e.steps",
    "app.files.tests.e2e.steps",
    "app.organizations.tests.e2e.steps",
]


def pytest_addoption(parser):
    parser.addoption("--driver", default="api", choices=["api", "browser"])


@pytest.fixture
def clock():
    """The test clock for date-pinning steps — independent of the driver."""
    return test_clock


@pytest.fixture(autouse=True)
def reset_clock(monkeypatch):
    """Route app.shared.clock.now onto the test clock, and unpin it after the test.

    Both drivers run the app in-process, so a plain monkeypatch reaches every
    runtime clock.now() call — including the in-thread browser server.
    """
    monkeypatch.setattr("app.shared.clock.now", test_clock.now)
    yield
    test_clock.reset()


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
