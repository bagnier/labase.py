from collections.abc import Generator

import pytest
from dotenv import load_dotenv

from tests.bdd.drivers.browser import BrowserDriver

pytest_plugins = ["tests.bdd.steps"]


def pytest_configure(config):
    load_dotenv(".env.test", override=True)

    from app.shared.config import get_settings
    from app.shared.supabase_client import get_supabase, get_supabase_admin

    get_settings.cache_clear()
    get_supabase.cache_clear()
    get_supabase_admin.cache_clear()


@pytest.fixture(scope="session")
def browser_driver() -> Generator[BrowserDriver, None, None]:
    d = BrowserDriver()
    d.start()
    yield d
    d.stop()
