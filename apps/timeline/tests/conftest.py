"""The reader the unit tests drive, and the engine hygiene it owes the tests after it.

``TimelineReader`` needs an admin session, and ``admin_session_factory`` is lru_cached: a session
opened here binds an asyncpg pool to *this* test's loop, and the next test to ask for one — the
e2e driver, on its own loop — gets that dead pool back and fails at setup with "Event loop is
closed". Disposing and clearing the caches on the way out is what keeps the two kinds of test
independent, the same shape ``apps/issues`` and ``apps/metrics`` use around their own DB fixtures.
"""

import pytest_asyncio

from apps.shared.persistence import database as db
from apps.timeline.infra.repository import TimelineReader


def _clear_engine_caches() -> None:
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


@pytest_asyncio.fixture
async def reader():
    # Cleared on the way *in* as well as out. Out alone was enough while the reader only touched
    # the two DB sources; now the ``logs`` source is a table too, so a driver-based test running
    # before this one leaves a pool bound to its dead loop and the read fails at teardown.
    _clear_engine_caches()
    async with db.admin_session_factory()() as session:
        yield TimelineReader(session)
    await db._admin_engine().dispose()
    _clear_engine_caches()
