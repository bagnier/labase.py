"""The event listener — reads the persisted journal and runs both deliveries off it.

``emit`` only writes a ``BusinessEvent`` to the ``business_events`` journal inside the request's
transaction (the bus's ``emit`` → ``EventRepository.record``). This listener reads that
journal, woken by its ``AFTER INSERT`` NOTIFY (poll as a net), and runs the deliveries the
producer no longer does — so it never knows its consumers nor waits for them:

- **``on`` / async fan-out — exactly-once, per declared consumer.** Each durable consumer (a queue
  topic) claims its own backlog off its own durable cursor (:meth:`EventRepository.topic_backlog`)
  — never a flag on the record itself, which would let whichever instance checked a fact first
  foreclose it for a consumer *that instance's* wiring simply does not carry (a rolling deploy; an
  app switched on and not yet restarted everywhere — README: `dispatch per declared consumer`). A
  fact is dispatched to a topic on first sight and the topic's cursor only advances past the
  contiguous *settled* prefix, so a still-unsettled retry is possible — the ``dispatched_consumers``
  ledger is what makes that retry a no-op rather than a second task (README: background work).
- **Routability, separately.** Each tick also claims un-checked records with ``FOR UPDATE SKIP
  LOCKED`` and stamps ``checked_at`` — bounding a single, unrelated concern: a fact whose ``kind``
  maps to no registered class can be routed to no one, ever, and is surfaced as an issue once.
- **``spread`` — per instance.** A settings reload must run on *every* process, so it cannot claim:
  each tick reads facts above this process's in-memory cursor whose kind has a ``spread``
  subscriber and runs those handlers in-process (idempotent, so a replay is harmless). That cursor
  trails a settle window, because a key is minted at INSERT and a late commit would otherwise land
  under it unseen — the window is the only bound on how far under.
- **Reconstruct from the record.** Every path rebuilds the typed event from the record's ``kind``
  via the catalog's ``class_for``.
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

# How long a fact stays replayable before a cursor (spread's, or a durable consumer's own) is
# allowed past it. A key is minted at INSERT, so a fact can surface below a cursor that already
# passed it (see ``scan_spread``); the only thing bounding how far below is how long its
# transaction stayed open. This is that bound, stated — well past any request or queue task, and
# paid for only by re-reading an indexed range of facts nobody is producing most of the time.
SETTLE_SECONDS = 60.0


class UnroutableFact(Exception):
    """A persisted fact the listener cannot route: its ``kind`` maps to no registered event class,
    so no consumer could ever be handed it. Raised only to give the capture seam a live exception
    to fingerprint on — caught immediately, logged, and the record is still marked checked."""


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
        """One pass of every delivery path. Returns the routability-check count, which is what
        drives the drain loop's batching for that pass — the backlog dispatch and the spread scan
        each find their own way to the end of what is ready for them.

        - **routability** — claim a batch of never-checked facts (``FOR UPDATE SKIP LOCKED``),
          surface an unrecognized ``kind`` as an issue, stamp them checked. Bounds one concern
          only: whether a fact can be routed at all, never whether a consumer got it (that is
          :meth:`_dispatch_backlog`, entirely independent of this marker — README: `dispatch per
          declared consumer`).
        - **``on`` / async** — see :meth:`_dispatch_backlog`.
        - **``spread``** — read facts newer than this process's cursor whose kind has a ``spread``
          subscriber and run those handlers **in-process** (config reload). No claim, no mark:
          every instance replays them.
        """
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

        Each fact above a topic's cursor is dispatched on first sight, immediately — the ledger
        (:meth:`~apps.shared.events.repository.EventRepository.dispatch_consumer`) is what makes a
        retry, before the cursor has caught up to the settle window, a no-op rather than a second
        task."""
        for event_type, reactions in self._wiring.reactions().items():
            kind = event_type.kind
            for reaction in reactions:
                cursor = await repo.lock_dispatch_cursor(reaction.topic)
                if cursor is None:
                    continue  # another instance holds this topic's cursor this tick
                found, settled_cursor = await repo.topic_backlog(
                    kind, cursor, self._settle, self._batch
                )
                for record in found:
                    if await repo.dispatch_consumer(record.id, reaction.topic):
                        payload = task_payload(record)
                        actor = record.user_id if reaction.as_actor else None
                        await enqueue(session, reaction.topic, payload, user_id=actor)
                if settled_cursor != cursor:
                    await repo.advance_dispatch_cursor(reaction.topic, settled_cursor)

    async def _read_spread(self, repo: EventRepository) -> list[BusinessEventRecord]:
        """Facts above the spread cursor whose kind has a ``spread`` subscriber, minus the ones
        this process already applied while they sat inside the settle window.

        The cursor trails the window on purpose, so a fact that commits late still surfaces above
        it (see ``scan_spread``). What that costs is the same fact offered on every tick until it
        settles, and this set is what keeps the handler from being run again for it — the reason
        a late commit is caught without a config reload firing sixty times over.
        """
        kinds = self._wiring.spread_kinds()
        if not kinds:
            return []
        # Nil-uuid sentinel on first pass: uuid7 is version-tagged, so it always sorts above nil.
        cursor = self._spread_cursor if self._spread_cursor is not None else uuid.UUID(int=0)
        found, settled = await repo.scan_spread(cursor, kinds, self._settle)
        fresh = [record for record in found if record.id not in self._spread_applied]
        self._spread_cursor = settled
        # Only what the cursor has not passed: below it nothing is ever scanned again, so
        # remembering it would grow this set for the life of the process.
        self._spread_applied = {record.id for record in found if record.id > settled}
        return fresh

    async def _apply_spread(self, record: BusinessEventRecord) -> None:
        """Reconstruct the fact and run its ``spread`` handlers on this instance, then advance the
        cursor.

        A handler that raises leaves *this* instance running on stale config while every other one
        moved on, and nothing will retry it: spread has no claim, no queue and no ledger. So it is
        a defect, logged at ``exception`` level — the capture seam folds it into a console Issue —
        exactly like a record that cannot be rebuilt at all (a field added to the event class after
        the fact was written, a hand-inserted payload). Not a loop, hence no transition rule: these
        run when an admin edits a setting, not once a second.

        The record counts as applied either way, refused or unrebuildable: ``_read_spread`` books
        it on the way out, so a fact this process can never make sense of is passed over once
        rather than replayed until the window closes and then forgotten anyway."""
        event = self._reconstruct(record)
        if event is not None:
            for handler in self._wiring.spread_handlers_for(event):
                try:
                    await handler(event)
                except Exception as exc:
                    log.exception("listener.spread_handler_failed", exc_info=exc, kind=record.kind)

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

    @staticmethod
    def _capture_unroutable(record: BusinessEventRecord) -> None:
        """Log an unroutable fact at ``exception`` level so the capture seam records a console
        Issue. Raised-and-caught to give the capture fingerprint a live traceback; the caller marks
        the record checked regardless, so a fact we cannot route never wedges the claim."""
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
