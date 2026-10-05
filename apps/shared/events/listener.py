"""The event listener: delivers reactions off the journal after commit, woken by its ``AFTER
INSERT`` NOTIFY and polling as a net.

- ``on`` consumers, once per declared consumer: each topic dispatches off its own durable cursor,
  never off a flag on the fact, and the ``dispatched_consumers`` ledger makes a retry a no-op
  (AGENTS: deferred work rides a durable Postgres queue).
- Routability: each tick claims unchecked facts and stamps ``checked_at``; a ``kind`` no class
  claims is surfaced as an issue once.
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

# The longest a fact's transaction may stay open and still be seen by a cursor, spread's or a
# consumer's (see ``facts_above_cursor``): well past any request or task, at the cost of
# re-reading a small indexed range.
SETTLE_SECONDS = 60.0


def _kinds_of(event_type: type[BusinessEvent]) -> list[str]:
    """Every catalog-registered kind whose class is ``event_type`` or one of its subclasses — the
    inverse of :meth:`~apps.shared.events.wiring.EventWiring.consumers_of`'s MRO walk, needed here
    because a fact's *own* concrete kind is what the journal is queried by, not the (possibly
    abstract) type a reaction was registered against."""
    return [kind for kind, cls in catalog.kinds().items() if issubclass(cls, event_type)]


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
        settle_seconds: float = SETTLE_SECONDS,
    ) -> None:
        self._interval = interval_seconds
        self._batch = batch_size
        self._session_factory = session_factory
        self._wiring = wiring if wiring is not None else process_wiring
        self._settle = settle_seconds
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
        """One pass of every delivery. Returns how many facts the routability claim checked, so
        the caller drains until zero; the backlog dispatch and the spread scan each read to the
        end of what is ready."""
        async with self._session() as session:
            repo = EventRepository(session)
            checked = await repo.claim_unchecked(self._batch)
            for record in checked:
                self._check_routable(record)
            if checked:
                await repo.mark_checked([r.id for r in checked])
            await self._dispatch_backlog(session, repo)
            spread_records = await self._read_spread(repo)
            await session.commit()
        for record in spread_records:
            await self._apply_spread(record)
        return len(checked)

    def _check_routable(self, record: BusinessEventRecord) -> None:
        """Surface a fact whose ``kind`` maps to no registered class — it can be routed to no one,
        ever, so this is the one thing worth checking once and remembering (via ``checked_at``)."""
        if catalog.class_for(record.kind) is None:
            self._capture_unroutable(record)

    async def _dispatch_backlog(self, session: AsyncSession, repo: EventRepository) -> None:
        """Deliver each durable consumer's own backlog off its own cursor — never off whether
        *this* tick's routability claim touched a record, which is a different instance's wiring
        away from knowing whether that consumer exists at all. A topic this instance's wiring
        lacks (a disabled app, an older deploy) is simply not iterated here, so it neither claims
        nor forecloses anything for a wiring that does carry it.

        Each fact above a topic's cursor is dispatched on first sight, immediately, unbounded —
        the same shape :meth:`_read_spread` reads (:meth:`~EventRepository.facts_above_cursor`),
        so a burst larger than one batch is never left waiting behind its own cursor. The ledger
        (:meth:`~EventRepository.dispatch_consumer`) is what makes a retry, before the cursor has
        caught up to the settle window, a no-op rather than a second task."""
        reactions_by_type = self._wiring.reactions()
        if not reactions_by_type:
            return
        settled_before = await repo.settled_before(self._settle)
        for event_type, reactions in reactions_by_type.items():
            kinds = _kinds_of(event_type)
            for reaction in reactions:
                cursor = await repo.lock_dispatch_cursor(reaction.topic)
                if cursor is None:
                    continue  # another instance holds this topic's cursor this tick
                found, settled_cursor = await repo.facts_above_cursor(cursor, kinds, settled_before)
                for record in found:
                    if await repo.dispatch_consumer(record.id, reaction.topic):
                        payload = task_payload(record)
                        actor = record.user_id if reaction.as_actor else None
                        await enqueue(session, reaction.topic, payload, user_id=actor)
                if settled_cursor != cursor:
                    await repo.advance_dispatch_cursor(reaction.topic, settled_cursor)

    async def _read_spread(self, repo: EventRepository) -> list[BusinessEventRecord]:
        """Spread facts not yet applied. The cursor trails the settle window, so a fact comes
        back on each tick until it settles; ``_spread_applied`` stops it running twice."""
        kinds = self._wiring.spread_kinds()
        if not kinds:
            return []
        # Every uuid7 sorts above nil.
        cursor = self._spread_cursor if self._spread_cursor is not None else uuid.UUID(int=0)
        settled_before = await repo.settled_before(self._settle)
        found, settled = await repo.facts_above_cursor(cursor, kinds, settled_before)
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

    @staticmethod
    def _capture_unroutable(record: BusinessEventRecord) -> None:
        """A bug, logged as an exception; the caller still marks the fact checked, so it never
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
