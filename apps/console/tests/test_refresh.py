from unittest.mock import AsyncMock, patch

import pytest

from apps.console.infra.refresh import SettingsRefresher
from apps.shared.host import Host
from apps.shared.settings import SettingsChanged


def _refresher(host: Host) -> SettingsRefresher:
    return SettingsRefresher(host.events, interval_seconds=30)


def _recording(host: Host) -> list[SettingsChanged]:
    events: list[SettingsChanged] = []

    async def record(event: SettingsChanged) -> None:
        events.append(event)

    host.events.on(SettingsChanged, record)
    return events


@pytest.mark.asyncio
async def test_first_tick_snapshots_without_emitting():
    host = Host()
    events = _recording(host)
    refresher = _refresher(host)
    with patch.object(
        refresher, "_read_all", AsyncMock(return_value={"files": {"max_upload_mb": "25"}})
    ):
        await refresher.tick()
    assert events == []


@pytest.mark.asyncio
async def test_changed_values_are_reemitted_locally():
    host = Host()
    events = _recording(host)
    refresher = _refresher(host)
    with patch.object(
        refresher,
        "_read_all",
        AsyncMock(
            side_effect=[
                {"files": {"max_upload_mb": "25"}, "todo": {"enabled": "true"}},
                {"files": {"max_upload_mb": "50"}, "todo": {"enabled": "true"}},
            ]
        ),
    ):
        await refresher.tick()
        await refresher.tick()
    assert events == [SettingsChanged("files", {"max_upload_mb": "50"})]


@pytest.mark.asyncio
async def test_absorbed_local_edit_is_not_reemitted():
    host = Host()
    events = _recording(host)
    refresher = _refresher(host)
    host.events.on(SettingsChanged, refresher.absorb)
    with patch.object(
        refresher,
        "_read_all",
        AsyncMock(
            side_effect=[
                {"files": {"max_upload_mb": "25"}},
                {"files": {"max_upload_mb": "50"}},
            ]
        ),
    ):
        await refresher.tick()
        # the console POST already emitted locally; absorb records the fresh values
        await host.events.emit(SettingsChanged("files", {"max_upload_mb": "50"}))
        events.clear()
        await refresher.tick()
    assert events == []


@pytest.mark.asyncio
async def test_zero_interval_never_starts():
    refresher = SettingsRefresher(Host().events, interval_seconds=0)
    await refresher.start()
    assert refresher._task is None
    await refresher.stop()
