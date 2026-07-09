"""Per-process flush of the in-memory accumulator to Postgres.

Same lifespan-task shape as ``SettingsRefresher``. Each process writes its own
rows (keyed by a random instance id) — multi-instance is correct by summing in
the read path, no coordination needed. The accumulator stays cumulative for the
Prometheus exposition; this task persists the deltas between ticks.
"""

import asyncio
import contextlib
import uuid

import structlog

from apps.metrics.infra.repository import add_deltas
from apps.shared import clock
from apps.shared.observability.metrics import (
    MetricsSnapshot,
    accumulator,
    snapshot_deltas,
)
from apps.shared.persistence.database import admin_session_factory

log = structlog.get_logger("labase.metrics.flush")


class MetricsFlusher:
    def __init__(self, interval_seconds: float) -> None:
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None
        self._instance = uuid.uuid4().hex[:8]
        self._previous: MetricsSnapshot = {}

    async def start(self) -> None:
        if self._interval > 0 and self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def tick(self) -> None:
        snapshot = accumulator.snapshot()
        deltas = snapshot_deltas(self._previous, snapshot)
        if deltas:
            minute = clock.now().replace(second=0, microsecond=0)
            async with admin_session_factory()() as session:
                await add_deltas(session, instance=self._instance, bucket=minute, deltas=deltas)
                await session.commit()
        # Advance only after a successful write, so a failed flush is retried
        # next tick instead of dropping the interval's traffic.
        self._previous = snapshot

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.tick()
            except Exception:
                log.warning("metrics.flush_failed")
