"""The reader the unit tests drive. Engine caches are cleared around it: a pool bound to this
test's loop would fail the next test with "Event loop is closed"."""

import pytest_asyncio

from apps.shared.persistence import database as db
from apps.timeline.infra.repository import TimelineReader


def _clear_engine_caches() -> None:
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


@pytest_asyncio.fixture
async def reader():
    # On the way in too: an earlier driver-based test may have left a dead pool.
    _clear_engine_caches()
    async with db.admin_session_factory()() as session:
        yield TimelineReader(session)
    await db._admin_engine().dispose()
    _clear_engine_caches()
