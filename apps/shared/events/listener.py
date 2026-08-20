"""The event listener — reads the persisted journal and runs both deliveries off it.

``emit`` only writes a ``BusinessEvent`` to the ``business_events`` journal inside the request's
transaction (the bus's ``emit`` → ``EventRepository.record``). This listener reads that
journal, woken by its ``AFTER INSERT`` NOTIFY (poll as a net), and runs the two deliveries the
producer no longer does — so it never knows its consumers nor waits for them:

- **``on`` / async fan-out — exactly-once, cluster-wide.** Each tick claims un-dispatched records
  with ``FOR UPDATE SKIP LOCKED`` and, in the same transaction, enqueues one queued task per
  registered ``bus.on`` consumer (read from the wiring via ``consumers_of``) and stamps
  ``dispatched_at``. No sequence-visibility gap, and N instances never double-fan a fact.
- **``spread`` — per instance.** A settings reload must run on *every* process, so it cannot claim:
  each tick reads facts newer than this process's in-memory cursor whose kind has a ``spread``
  subscriber and runs those handlers in-process (idempotent, so a replay is harmless).
- **Reconstruct from the record.** Both paths rebuild the typed event from the record's ``kind``
  via the catalog's ``class_for``; the async dedup key is the record id.
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


class UnroutableFact(Exception):
    """A persisted fact the listener cannot route: its ``kind`` maps to no registered event class,
    so no consumer could ever be handed it. Raised only to give the capture seam a live exception
    to fingerprint on — caught immediately, logged, and the record is still marked dispatched."""


class EventListener:
    """The journal's reader, ticking on its own task.

    Delivering is where the two halves of the event system meet, and the only place they do: the
    *catalog* says what a record is, the *wiring* says who wants it. Both are imported, so the
    listener reads what a mount declared without holding the bus that wrote it — and a test can hand
    over a ``wiring`` of its own to deliver against isolated subscriptions.

    ``session_factory`` likewise overrides the admin session: the API test driver injects its
    rolled-back test connection, so the listener sees the same uncommitted facts a request just
    wrote.
    """

    def __init__(
        self,
        interval_seconds: float,
        batch_size: int = 50,
        session_factory: Callable[[], AsyncSession] | None = None,
        wiring: EventWiring | None = None,
    ) -> None:
        self._interval = interval_seconds
        self._batch = batch_size
        self._session_factory = session_factory
        self._wiring = wiring if wiring is not None else process_wiring
        self._spread_cursor: uuid.UUID | None = None  # per-instance high-water (uuid7, ordered)
        self._task: asyncio.Task | None = None
        self._listen_conn: Any | None = None
        self._wake = asyncio.Event()
        self._health = LoopHealth(log, "listener.tick")

    def _session(self) -> AsyncSession:
        factory = self._session_factory or admin_session_factory()
        return factory()

    async def tick(self) -> int:
        """One pass of both delivery paths. Returns the ``on``-path count, which is what drives
        the drain loop's batching — the spread scan has no ``LIMIT``, so one tick applies all of it
        and never needs another pass.

        - **``on`` / async** — claim a batch of never-dispatched facts (``FOR UPDATE SKIP LOCKED``),
          enqueue one task per durable consumer, stamp them dispatched. Exactly-once cluster-wide;
          the tasks and the mark commit together.
        - **``spread``** — read facts newer than this process's cursor whose kind has a ``spread``
          subscriber and run those handlers **in-process** (config reload). No claim, no dispatched
          mark: every instance replays them.
        """
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
        """Facts newer than the spread cursor whose kind has a ``spread`` subscriber."""
        kinds = self._wiring.spread_kinds()
        if not kinds:
            return []
        # Nil-uuid sentinel on first pass: uuid7 is version-tagged, so it always sorts above nil.
        cursor = self._spread_cursor if self._spread_cursor is not None else uuid.UUID(int=0)
        return await repo.scan_spread(cursor, kinds)

    async def _apply_spread(self, record: BusinessEventRecord) -> None:
        """Reconstruct the fact and run its ``spread`` handlers on this instance, then advance the
        cursor.

        A handler that raises leaves *this* instance running on stale config while every other one
        moved on, and nothing will retry it: spread has no claim, no queue and no ledger. So it is
        a defect, logged at ``exception`` level — the capture seam folds it into a console Issue —
        exactly like a record that cannot be rebuilt at all (a field added to the event class after
        the fact was written, a hand-inserted payload). Not a loop, hence no transition rule: these
        run when an admin edits a setting, not once a second.

        The cursor advances either way: it is a high-water mark, so leaving it on a record we can
        never process would replay that same fact forever and freeze propagation for good."""
        event = self._reconstruct(record)
        if event is not None:
            for handler in self._wiring.spread_handlers_for(event):
                try:
                    await handler(event)
                except Exception as exc:
                    log.exception("listener.spread_handler_failed", exc_info=exc, kind=record.kind)
        self._spread_cursor = record.id

    @staticmethod
    def _reconstruct(record: BusinessEventRecord) -> BusinessEvent | None:
        """Rebuild the typed event from a business_events record (its fields + scoping columns), or
        ``None`` when it cannot be — the caller skips such a record rather than stalling on it.

        A payload that no longer fits its event class is not skipped silently: a stored fact that
        stopped rebuilding (a field made required after the fact was written, a hand-inserted
        payload) is a defect, so it is logged at ``exception`` level — the capture seam folds it
        into a console Issue — not swallowed as a mere warning."""
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
            # Not the benign "known kind, nobody listens" no-op below: a fact was persisted that
            # this process cannot even name, and that is a defect worth an Issue of its own.
            self._capture_unroutable(record)
            return
        subs = self._wiring.consumers_of(event_type)
        if not subs:
            return  # known kind, nobody listens — a clean no-op, no fact is lost
        payload = task_payload(record)
        actor = record.user_id
        for sub in subs:
            await enqueue(session, sub.topic, payload, user_id=actor if sub.as_actor else None)

    @staticmethod
    def _capture_unroutable(record: BusinessEventRecord) -> None:
        """Log an unroutable fact at ``exception`` level so the capture seam records a console
        Issue. Raised-and-caught to give the capture fingerprint a live traceback; the caller marks
        the record dispatched regardless, so a fact we cannot route never wedges the cursor."""
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
        """One pass of both delivery paths, and the verdict its outcome earns.

        Split out of ``_run`` so the failure path is drivable: a listener that stops delivering
        leaves every fact's reactions unrun, and used to say so only at ``warning``.
        """
        try:
            while await self.tick():
                pass  # drain all ready facts before waiting
        except Exception as exc:
            self._health.tick_failed(exc)
        else:
            self._health.tick_succeeded()

    async def _run(self) -> None:
        while True:
            await self.guarded_tick()
            # Wake on NOTIFY, or poll after the interval as a durability net.
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval)
            self._wake.clear()

    async def _listen(self) -> None:
        """Open a dedicated connection LISTENing on the NOTIFY channel; a notification wakes the run
        loop for an immediate drain."""
        try:
            raw = await _user_engine().raw_connection()
            asyncpg_conn = raw.driver_connection
            if asyncpg_conn is None:
                raise RuntimeError("no asyncpg connection behind the pool")
            await asyncpg_conn.add_listener(NOTIFY_CHANNEL, self._on_notify)
            self._listen_conn = raw
        except Exception as exc:
            # No LISTEN (e.g. DB down at boot) — the poll loop still delivers, just not instantly.
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
