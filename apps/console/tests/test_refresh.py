import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from apps.console.infra.refresh import SettingsRefresher
from apps.shared.bus import EventBus
from apps.shared.host import Host
from apps.shared.persistence import database as db
from apps.shared.settings import SettingsChanged


def _clear_engine_caches() -> None:
    db._user_engine.cache_clear()
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


@pytest_asyncio.fixture
async def fresh_engines():
    # This test opens real LISTEN/NOTIFY connections, so the engines must be built on — and disposed
    # from — this test's loop (mirrors the tailer's DB-test isolation).
    _clear_engine_caches()
    yield
    await db._user_engine().dispose()
    await db._admin_engine().dispose()
    _clear_engine_caches()


async def _noop(event: SettingsChanged) -> None:
    return None


@pytest.mark.asyncio
async def test_tick_delivers_each_apps_fresh_settings_to_the_bus():
    # On a spread NOTIFY (or its interval net), the refresher re-reads every app and hands the fresh
    # values to the bus's spread handlers via deliver_spread — no snapshot/diff, since a reload is
    # idempotent so re-applying unchanged values is a no-op.
    host = Host()
    delivered: list[SettingsChanged] = []

    async def capture(event: SettingsChanged) -> None:
        delivered.append(event)

    refresher = SettingsRefresher(host.events, interval_seconds=30)
    with (
        patch.object(host.events, "deliver_spread", capture),
        patch.object(
            refresher,
            "_read_all",
            AsyncMock(return_value={"files": {"max_upload_mb": "50"}, "todo": {"enabled": "true"}}),
        ),
    ):
        await refresher.tick()

    assert delivered == [
        SettingsChanged("files", {"max_upload_mb": "50"}),
        SettingsChanged("todo", {"enabled": "true"}),
    ]


@pytest.mark.asyncio
async def test_a_spread_notify_wakes_a_listening_refresher(fresh_engines):
    # The real NOTIFY→LISTEN wire (not the drive_spread shortcut): a refresher holding an open
    # LISTEN must wake when emit fires a spread NOTIFY on a committed transaction. The interval is
    # long enough that only the NOTIFY — never the poll — could have woken it.
    bus = EventBus()
    bus.spread(SettingsChanged, _noop)  # so emit decides to broadcast for this type
    refresher = SettingsRefresher(bus, interval_seconds=3600)
    await refresher._listen()
    try:
        refresher._wake.clear()
        async with db.admin_session_factory()() as session:
            await bus.emit(SettingsChanged("files", {}), session=session)
            await session.commit()  # a NOTIFY is delivered to LISTENers on commit
        await asyncio.wait_for(refresher._wake.wait(), timeout=5)
        assert refresher._wake.is_set()
    finally:
        await refresher._unlisten()


@pytest.mark.asyncio
async def test_zero_interval_never_starts():
    refresher = SettingsRefresher(Host().events, interval_seconds=0)
    await refresher.start()
    assert refresher._task is None
    await refresher.stop()
