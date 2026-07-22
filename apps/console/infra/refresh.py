"""Cross-instance settings freshness — the SpreadListener for ``SettingsChanged``.

A settings edit is a "run everywhere" event: every process must re-point its in-memory
``AppSettings`` handles. ``emit(SettingsChanged, session)`` fires a NOTIFY on the ``spread`` channel
(:data:`~apps.shared.events.bus.SPREAD_CHANNEL`); each process runs this listener, which — woken by
the NOTIFY, or by its interval as a durability net — re-reads ``app_settings`` and applies the bus's
``spread`` handlers (pulled via :meth:`~apps.shared.events.bus.EventBus.spread_handlers`).

The emitter is just another listener: it applies via its own LISTEN, once. Re-applying every app's
current values on each wake is deliberate and safe — ``spread`` handlers are idempotent (a reload is
a plain assignment), so there is no snapshot to diff and no self-dedup to track.
"""

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events.bus import SPREAD_CHANNEL, EventBus
from apps.shared.persistence.database import _user_engine, admin_session_factory
from apps.shared.persistence.settings_store import AppSetting
from apps.shared.settings import SettingsChanged

log = structlog.get_logger("labase.settings.refresh")


class SettingsRefresher:
    def __init__(
        self,
        bus: EventBus,
        interval_seconds: float,
        session_factory: Callable[[], AsyncSession] | None = None,
    ) -> None:
        # session_factory overrides the admin session (the API test driver injects its rolled-back
        # test connection so a driven tick sees the same uncommitted change a request just wrote).
        self._bus = bus
        self._interval = interval_seconds
        self._session_factory = session_factory
        self._task: asyncio.Task | None = None
        self._listen_conn: Any | None = None
        self._wake = asyncio.Event()

    def _session(self) -> AsyncSession:
        factory = self._session_factory or admin_session_factory()
        return factory()

    async def _read_all(self) -> dict[str, dict[str, str]]:
        async with self._session() as session:
            rows = (
                await session.execute(select(AppSetting.app, AppSetting.key, AppSetting.value))
            ).all()
        grouped: dict[str, dict[str, str]] = {}
        for app, key, value in rows:
            grouped.setdefault(app, {})[key] = value
        return grouped

    async def tick(self) -> None:
        """Re-read every app's settings and apply the bus's spread handlers. Idempotent —
        applying unchanged values is a no-op, so no snapshot/diff is needed."""
        for app, values in (await self._read_all()).items():
            event = SettingsChanged(app_name=app, values=values)
            for handler in self._bus.spread_handlers(event):
                await handler(event)

    async def start(self) -> None:
        if self._interval > 0 and self._task is None:
            await self._listen()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._unlisten()

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.warning("settings.refresh_failed")
            # Wake on a spread NOTIFY, or re-read after the interval as a durability net.
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval)
            self._wake.clear()

    async def _listen(self) -> None:
        """Open a dedicated connection LISTENing on the spread channel; a notification wakes the run
        loop for an immediate re-read."""
        try:
            raw = await _user_engine().raw_connection()
            asyncpg_conn = raw.driver_connection
            await asyncpg_conn.add_listener(SPREAD_CHANNEL, self._on_notify)
            self._listen_conn = raw
        except Exception:
            # No LISTEN (e.g. DB down at boot) — the interval poll still converges, just not now.
            log.warning("settings.listen_failed")

    async def _unlisten(self) -> None:
        conn = self._listen_conn
        self._listen_conn = None
        if conn is not None:
            with contextlib.suppress(Exception):
                await conn.driver_connection.remove_listener(SPREAD_CHANNEL, self._on_notify)
            with contextlib.suppress(Exception):
                await conn.close()

    def _on_notify(self, *_: Any) -> None:
        self._wake.set()
