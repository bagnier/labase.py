import asyncio
import os

os.environ.setdefault("ENV_FILE", ".env.test")

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import tests.db as db
from app.auth.infra.session import get_rls_session
from app.main import app
from app.shared.config import get_settings
from app.shared.persistence.database import _admin_engine, get_admin_session, get_user_session
from tests.e2e.drivers.api import ApiDriver
from tests.e2e.drivers.browser import BrowserDriver

pytest_plugins = [
    "app.auth.tests.steps",
    "app.console.tests.steps",
    "app.profile.tests.steps",
    "app.todo.tests.steps",
    "app.files.tests.steps",
    "app.organizations.tests.steps",
]


def pytest_addoption(parser):
    parser.addoption("--driver", default="api", choices=["api", "browser"])


@pytest.fixture(autouse=True)
def db_rollback(driver: ApiDriver | BrowserDriver):
    """Chaque test/scénario s'exécute dans une transaction rollbackée à la fin.

    Toutes les sessions (user, admin, rls) partagent la même connexion postgres sur
    laquelle SQLAlchemy émet des SAVEPOINTs. conn.rollback() en teardown annule tout.
    set_rls_context est bypassé (la connexion postgres a BYPASSRLS) — les tests RLS
    restent dans test_rls.py avec la fixture db_session.
    """
    if not isinstance(driver, ApiDriver):
        yield
        db.truncate_app_tables()
        return

    conn = driver._run(db.begin_test_transaction(_admin_engine()))
    db._test_connection = conn
    app.dependency_overrides[get_user_session] = db.override_get_session
    app.dependency_overrides[get_admin_session] = db.override_get_session
    app.dependency_overrides[get_rls_session] = db.override_get_rls_session
    yield
    app.dependency_overrides.pop(get_user_session, None)
    app.dependency_overrides.pop(get_admin_session, None)
    app.dependency_overrides.pop(get_rls_session, None)
    db._test_connection = None
    driver._run(db.end_test_transaction(conn))
    driver.cleanup_test_orgs()
    driver.cleanup_test_auth_users()


@pytest_asyncio.fixture()
async def db_session():
    """Session transactionnelle rollbackée pour tests d'intégration directs (sans HTTP)."""
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
        asyncio.run(db.purge_leftover_test_data())

    request.addfinalizer(finalize)
    return d
