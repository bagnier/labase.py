"""On the API lane's shared connection, each session still runs as its own role (``app_rls`` or
``postgres``), or no scenario would meet a policy."""

import pytest
from sqlalchemy import text

from apps.auth.infra.session import get_rls_session
from tests.e2e.drivers import api_transaction as db
from tests.e2e.drivers.api import ApiDriver


@pytest.fixture
def api(driver) -> ApiDriver:
    if not isinstance(driver, ApiDriver):
        pytest.skip("API-driver meta-test")
    return driver


async def _roles_in_turn() -> tuple[str, str, str]:
    """RLS, admin, RLS again, as one request may interleave them."""
    user_sessions = db.override_get_session()
    admin_sessions = db.override_get_session()
    user = await anext(user_sessions)
    admin = await anext(admin_sessions)
    rls_sessions = get_rls_session(current_user=None, session=user)
    rls = await anext(rls_sessions)
    try:
        return (
            await rls.scalar(text("select current_user")),
            await admin.scalar(text("select current_user")),
            await rls.scalar(text("select current_user")),
        )
    finally:
        for sessions in (rls_sessions, admin_sessions, user_sessions):
            await sessions.aclose()


def test_the_rls_session_runs_as_the_app_role_and_the_admin_one_does_not(api: ApiDriver) -> None:
    roles = api.run(_roles_in_turn())

    assert roles == ("app_rls", "postgres", "app_rls")
