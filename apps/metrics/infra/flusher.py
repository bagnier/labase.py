"""Each process flushes its accumulator's deltas to its own rows (by instance id); reads sum
them, so instances need no coordination.
"""

import asyncio
import contextlib
import uuid

import structlog

from apps.metrics.domain.accumulator import (
    MetricsSnapshot,
    accumulator,
    snapshot_deltas,
)
from apps.metrics.infra.repository import add_deltas
from apps.shared import clock
from apps.shared.logs.loop import LoopHealth
from apps.shared.persistence.database import admin_session_factory

log = structlog.get_logger(__name__)


class MetricsFlusher:
    def __init__(self, interval_seconds: float) -> None:
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None
        self._instance = uuid.uuid4().hex[:8]
        self._previous: MetricsSnapshot = {}
        self._health = LoopHealth(log, "metrics.flush")

    async def start(self) -> None:
        if self._interval > 0 and self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        # Else every deploy dips the Load screen. Guarded: losing the interval must not fail
        # the stop.
        try:
            await self.tick()
        except Exception as exc:
            log.warning("metrics.flush_failed", exc_info=exc)

    async def tick(self) -> None:
        snapshot = accumulator.snapshot()
        deltas = snapshot_deltas(self._previous, snapshot)
        if deltas:
            minute = clock.now().replace(second=0, microsecond=0)
            async with admin_session_factory()() as session:
                await add_deltas(
                    session, instance=self._instance, bucket_start=minute, deltas=deltas
                )
                await session.commit()
        # Only after a successful write, so a failed flush is retried.
        self._previous = snapshot

    async def guarded_tick(self) -> None:
        """One flush, reported to the loop verdict. Public so tests can drive the failure path."""
        try:
            await self.tick()
        except Exception as exc:
            self._health.tick_failed(exc)
        else:
            self._health.tick_succeeded()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            await self.guarded_tick()
