"""The pytest entry point (``-p tests.plugin``): the clock, ``--driver``, the shared steps and
the driver fixtures, for tests under both ``apps/`` and ``tests/``.
"""

import os

os.environ.setdefault("ENV_FILE", ".env.test")

# pytest-xdist (`-n`, experimental): each worker gets its own schema, bucket and e2e port, set
# before settings are first read, and provisioned here since reset_app_switches() below needs it.
# Not safe for the browser suite: workers share auth.users, so same-email and admin-role
# scenarios collide; `make ci` stays serial. One conditional block, for E402.
if os.environ.get("PYTEST_XDIST_WORKER"):
    _worker = os.environ["PYTEST_XDIST_WORKER"]
    os.environ["SUPABASE_DATABASE_SCHEMA"] = f"test_{_worker}"
    os.environ["SUPABASE_STORAGE_BUCKET"] = f"org-files-test-{_worker}"
    # 8801+index stays within the WebAuthn rp_origins listed in supabase/config.toml.
    os.environ["LABASE_E2E_PORT"] = str(8801 + int(_worker.removeprefix("gw")))
    from scripts.provision_schema import provision

    provision(f"test_{_worker}", f"org-files-test-{_worker}", reset=True)

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import tests.e2e.clock as test_clock
from apps.shared.settings.env import get_technical_settings
from tests.e2e import cleanup

# Before the plugins below import ``apps.main``, which reads the switches at import.
cleanup.reset_app_switches()
cleanup.disable_welcome_seeding()

pytest_plugins = [
    "tests.e2e.plugin",
    "tests.e2e.steps_common",
    "apps.auth.tests.e2e.steps",
    "apps.api_keys.tests.e2e.steps",
    "apps.issues.tests.e2e.steps",
    "apps.metrics.tests.e2e.steps",
    "apps.timeline.tests.e2e.steps",
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
    """Skip a @web scenario (about rendered pages) on the API driver."""
    if item.get_closest_marker("web") and item.config.getoption("--driver") != "browser":
        pytest.skip("web-only scenario; runs under the browser driver")


@pytest.fixture
def clock():
    return test_clock


@pytest.fixture(autouse=True)
def reset_clock(monkeypatch):
    """Patch ``apps.shared.clock.now`` with the test clock; both drivers run the app
    in-process."""
    monkeypatch.setattr("apps.shared.clock.now", test_clock.now)
    yield
    test_clock.reset()


@pytest_asyncio.fixture()
async def db_session():
    """An RLS-enforced session for tests without HTTP, in one transaction rolled back after."""
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
