"""The event listener: delivers reactions off the journal after commit, woken by its ``AFTER
INSERT`` NOTIFY and polling as a net.

- ``on`` consumers, once cluster-wide: claim undispatched facts, enqueue one task per consumer and
  mark them dispatched in one transaction (AGENTS: deferred work rides a durable Postgres queue).
- ``spread`` handlers, on every instance: replay facts above a per-process cursor, in-process.
"""

import asyncio
import contextlib
import uuid
from collections.abc import Callable
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events.catalog import catalog
from apps.shared.events.models import BusinessEventRecord
from apps.shared.events.repository import EventRepository, task_payload
from apps.shared.events.types import BusinessEvent
from apps.shared.events.wiring import EventWiring
from apps.shared.events.wiring import wiring as process_wiring
from apps.shared.logs.loop import LoopHealth
from apps.shared.persistence.database import _user_engine, admin_session_factory
from apps.shared.queue import enqueue

log = structlog.get_logger(__name__)

NOTIFY_CHANNEL = "business_event"

# The longest a fact's transaction may stay open and still be seen by ``spread`` (see
# ``scan_spread``): well past any request or task, at the cost of re-reading a small indexed range.
SPREAD_SETTLE_SECONDS = 60.0


class UnroutableFact(Exception):
    """A stored fact whose ``kind`` no event class claims. Raised and caught at once, to give
    the capture seam a traceback to fingerprint."""


class EventListener:
    """The journal's reader, ticking on its own task. The catalog says what a record is, the
    wiring who wants it.

    ``wiring`` and ``session_factory`` default to the process's; the API test driver passes its
    rolled-back connection so the listener sees the facts a request just wrote.
    """

    def __init__(
        self,
        interval_seconds: float,
        batch_size: int = 50,
        session_factory: Callable[[], AsyncSession] | None = None,
        wiring: EventWiring | None = None,
        spread_settle_seconds: float = SPREAD_SETTLE_SECONDS,
    ) -> None:
        self._interval = interval_seconds
        self._batch = batch_size
        self._session_factory = session_factory
        self._wiring = wiring if wiring is not None else process_wiring
        self._spread_settle = spread_settle_seconds
        self._spread_cursor: uuid.UUID | None = None  # per-instance high-water, settled facts only
        self._spread_applied: set[uuid.UUID] = set()  # applied above it, still inside the window
        self._task: asyncio.Task | None = None
        self._listen_conn: Any | None = None
        self._wake = asyncio.Event()
        self._health = LoopHealth(log, "listener.tick")

    def _session(self) -> AsyncSession:
        factory = self._session_factory or admin_session_factory()
        return factory()

    async def tick(self) -> int:
        """One pass of both deliveries. Returns how many facts the ``on`` path claimed, so the
        caller drains until zero; the spread scan has no limit and needs one pass."""
        async with self._session() as session:
            repo = EventRepository(session)
            claimed = await repo.claim_undispatched(self._batch)
            for record in claimed:
                await self._fan_out(session, record)
            if claimed:
                await repo.mark_dispatched([r.id for r in claimed])
            spread_records = await self._read_spread(repo)
            await session.commit()
        for record in spread_records:
            await self._apply_spread(record)
        return len(claimed)

    async def _read_spread(self, repo: EventRepository) -> list[BusinessEventRecord]:
        """Spread facts not yet applied. The cursor trails the settle window, so a fact comes
        back on each tick until it settles; ``_spread_applied`` stops it running twice."""
        kinds = self._wiring.spread_kinds()
        if not kinds:
            return []
        # Every uuid7 sorts above nil.
        cursor = self._spread_cursor if self._spread_cursor is not None else uuid.UUID(int=0)
        found, settled = await repo.scan_spread(cursor, kinds, self._spread_settle)
        fresh = [record for record in found if record.id not in self._spread_applied]
        self._spread_cursor = settled
        # Below the cursor nothing is scanned again: forget it, or the set grows forever.
        self._spread_applied = {record.id for record in found if record.id > settled}
        return fresh

    async def _apply_spread(self, record: BusinessEventRecord) -> None:
        """Run the fact's ``spread`` handlers on this instance.

        A failing handler leaves this instance on stale config and nothing retries it, so it is
        logged as an exception (an issue). The fact counts as applied either way."""
        event = self._reconstruct(record)
        if event is not None:
            for handler in self._wiring.spread_handlers_for(event):
                try:
                    await handler(event)
                except Exception as exc:
                    log.exception("listener.spread_handler_failed", exc_info=exc, kind=record.kind)

    @staticmethod
    def _reconstruct(record: BusinessEventRecord) -> BusinessEvent | None:
        """The typed event, or ``None`` for the caller to skip. A payload that no longer fits its
        class is a bug: logged as an exception."""
        event_type = catalog.class_for(record.kind)
        if event_type is None:
            return None
        try:
            return event_type.from_payload(task_payload(record))
        except Exception:
            log.exception("listener.reconstruct_failed", kind=record.kind, event_id=str(record.id))
            return None

    async def _fan_out(self, session: AsyncSession, record: BusinessEventRecord) -> None:
        event_type = catalog.class_for(record.kind)
        if event_type is None:
            self._capture_unroutable(record)
            return
        subs = self._wiring.consumers_of(event_type)
        if not subs:
            return
        payload = task_payload(record)
        actor = record.user_id
        for sub in subs:
            await enqueue(session, sub.topic, payload, user_id=actor if sub.as_actor else None)

    @staticmethod
    def _capture_unroutable(record: BusinessEventRecord) -> None:
        """A bug, logged as an exception; the caller still marks the fact dispatched, so it never
        blocks the ones behind it."""
        try:
            raise UnroutableFact(f"no event class registered for kind {record.kind!r}")
        except UnroutableFact:
            log.exception("listener.unroutable_fact", kind=record.kind, event_id=str(record.id))

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

    async def guarded_tick(self) -> None:
        """Drain ready facts and report the outcome to the loop verdict
        (AGENTS: a failure that repeats is one bug). Public so tests can drive the failure path."""
        try:
            while await self.tick():
                pass
        except Exception as exc:
            self._health.tick_failed(exc)
        else:
            self._health.tick_succeeded()

    async def _run(self) -> None:
        while True:
            await self.guarded_tick()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval)
            self._wake.clear()

    async def _listen(self) -> None:
        """LISTEN on a dedicated connection; a notification wakes the run loop."""
        try:
            raw = await _user_engine().raw_connection()
            asyncpg_conn = raw.driver_connection
            if asyncpg_conn is None:
                raise RuntimeError("no asyncpg connection behind the pool")
            await asyncpg_conn.add_listener(NOTIFY_CHANNEL, self._on_notify)
            self._listen_conn = raw
        except Exception as exc:
            # The poll still delivers, only later.
            log.warning("listener.listen_failed", exc_info=exc)

    async def _unlisten(self) -> None:
        conn = self._listen_conn
        self._listen_conn = None
        if conn is not None:
            with contextlib.suppress(Exception):
                await conn.driver_connection.remove_listener(NOTIFY_CHANNEL, self._on_notify)
            with contextlib.suppress(Exception):
                await conn.close()

    def _on_notify(self, *_: Any) -> None:
        self._wake.set()
