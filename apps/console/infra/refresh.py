"""Cross-instance settings freshness — TTL re-read.

``SettingsChanged`` keeps the process that handled the console POST fresh; with
N instances the others served stale values silently. Each process runs this
refresher as a lifespan task: every ``settings_refresh_seconds`` it re-reads
``app_settings`` and re-emits a *local* ``SettingsChanged`` for each app whose
values changed, so every subscriber converges within one TTL. Local edits are
absorbed from the bus, so the emitting instance never re-emits its own change.
"""

import asyncio
import contextlib

import structlog
from sqlalchemy import select

from apps.shared.bus import EventBus
from apps.shared.persistence.database import admin_session_factory
from apps.shared.persistence.settings_store import AppSetting
from apps.shared.settings import SettingsChanged

log = structlog.get_logger("labase.settings.refresh")


class SettingsRefresher:
    def __init__(self, bus: EventBus, interval_seconds: float) -> None:
        self._bus = bus
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None
        self._snapshot: dict[str, dict[str, str]] | None = None

    async def start(self) -> None:
        if self._interval > 0 and self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def absorb(self, event: SettingsChanged) -> None:
        """Bus handler: a local edit is already fresh here — don't re-emit it next tick."""
        if self._snapshot is not None:
            self._snapshot[event.app_name] = dict(event.values)

    async def _read_all(self) -> dict[str, dict[str, str]]:
        async with admin_session_factory()() as session:
            rows = (
                await session.execute(select(AppSetting.app, AppSetting.key, AppSetting.value))
            ).all()
        grouped: dict[str, dict[str, str]] = {}
        for app, key, value in rows:
            grouped.setdefault(app, {})[key] = value
        return grouped

    async def tick(self) -> None:
        fresh = await self._read_all()
        if self._snapshot is not None:
            for app, values in fresh.items():
                if self._snapshot.get(app) != values:
                    log.info("settings.refreshed", app=app)
                    await self._bus.emit(SettingsChanged(app, values))
        self._snapshot = fresh

    async def _run(self) -> None:
        # First tick only snapshots: mount() already read the current values.
        while True:
            try:
                await self.tick()
            except Exception:
                log.warning("settings.refresh_failed")
            await asyncio.sleep(self._interval)
