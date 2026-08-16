"""The event listener — reads the persisted trail and runs both deliveries off it.

``emit`` only writes a ``BusinessEvent`` to the ``business_events`` trail inside the request's
transaction (the bus's ``emit`` → ``EventRepository.record``). This listener reads that
trail, woken by its ``AFTER INSERT`` NOTIFY (poll as a net), and runs the two deliveries the
producer no longer does — so it never knows its consumers nor waits for them:

- **``on`` / async fan-out — exactly-once, cluster-wide.** Each tick claims un-dispatched rows with
  ``FOR UPDATE SKIP LOCKED`` and, in the same transaction, enqueues one task-queue row per
  registered ``bus.on`` consumer (read from the registry via ``subscribers_for``) and stamps
  ``dispatched_at``. No sequence-visibility gap, and N instances never double-fan a row.
- **``spread`` — per instance.** A settings reload must run on *every* process, so it cannot claim:
  each tick reads facts newer than this process's in-memory cursor whose kind has a ``spread``
  subscriber and runs those handlers in-process (idempotent, so a replay is harmless).
- **Reconstruct from the row.** Both paths rebuild the typed event from the row's ``kind`` via the
  registry's ``event_class_for`` catalog; the async dedup key is the row id.
"""

import asyncio
import contextlib
import uuid
from collections.abc import Callable
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events.registry import EventRegistry
from apps.shared.events.registry import registry as process_registry
from apps.shared.events.repository import EventRepository, TrailRow, task_payload
from apps.shared.events.types import BusinessEvent
from apps.shared.persistence.database import _user_engine, admin_session_factory
from apps.shared.queue import enqueue

log = structlog.get_logger("labase.shared.listener")

NOTIFY_CHANNEL = "business_event"


class UnroutableFact(Exception):
    """A persisted fact the listener cannot route: its ``kind`` maps to no registered event class,
    so no consumer could ever be handed it. Raised only to give the capture seam a live exception
    to fingerprint on — caught immediately, logged, and the row is still marked dispatched."""


class EventListener:
    def __init__(
        self,
        interval_seconds: float,
        batch_size: int = 50,
        session_factory: Callable[[], AsyncSession] | None = None,
        registry: EventRegistry | None = None,
    ) -> None:
        # session_factory overrides the admin session (the API test driver injects its rolled-back
        # test connection, so the tailer sees the same uncommitted facts a request just wrote).
        self._interval = interval_seconds
        self._batch = batch_size
        self._session_factory = session_factory
        # The registry, not the bus: delivery reads *what exists and who listens*, and nothing the
        # bus adds on top. Taking it directly is what lets the type checker follow the four calls
        # below — through a bus they were `Any`, so a renamed registry method type-checked clean
        # and failed here at runtime. A test injects its own to isolate its subscriptions.
        self._registry = registry if registry is not None else process_registry
        self._spread_cursor: uuid.UUID | None = None  # per-instance high-water (uuid7, ordered)
        self._task: asyncio.Task | None = None
        self._listen_conn: Any | None = None
        self._wake = asyncio.Event()

    def _session(self) -> AsyncSession:
        factory = self._session_factory or admin_session_factory()
        return factory()

    async def tick(self) -> int:
        """One pass of both delivery paths. Returns how much work was processed.

        - **``on`` / async** — claim a batch of never-dispatched facts (``FOR UPDATE SKIP LOCKED``),
          enqueue one task per durable consumer, stamp them dispatched. Exactly-once cluster-wide;
          the tasks and the mark commit together.
        - **``spread``** — read facts newer than this process's cursor whose kind has a ``spread``
          subscriber and run those handlers **in-process** (config reload). No claim, no dispatched
          mark: every instance replays them.
        """
        async with self._session() as session:
            repo = EventRepository(session)
            rows = await repo.claim_undispatched(self._batch)
            for row in rows:
                await self._fan_out(session, row)
            if rows:
                await repo.mark_dispatched([r["id"] for r in rows])
            spread_rows = await self._read_spread(repo)
            await session.commit()
        for row in spread_rows:
            await self._apply_spread(row)
        # Return the on-path count only: it drives the drain loop's batching. The spread scan has no
        # LIMIT — a single tick applies all of it — so it never needs another pass.
        return len(rows)

    async def _read_spread(self, repo: EventRepository) -> list[TrailRow]:
        """Facts newer than the spread cursor whose kind has a ``spread`` subscriber."""
        kinds = self._registry.spread_kinds()
        if not kinds:
            return []
        # Nil-uuid sentinel on first pass: uuid7 is version-tagged, so it always sorts above nil.
        cursor = self._spread_cursor if self._spread_cursor is not None else uuid.UUID(int=0)
        return await repo.scan_spread(cursor, kinds)

    async def _apply_spread(self, row: TrailRow) -> None:
        """Reconstruct the fact and run its ``spread`` handlers on this instance, then advance the
        cursor. Handlers are idempotent (a reload is a plain assignment), so a failure is logged and
        skipped rather than blocking the cursor — and so is a row that cannot be rebuilt at all
        (a field added to the event class after the row was written, a hand-inserted payload).
        The cursor advances either way: it is a high-water mark, so leaving it on a row we can
        never process would replay that same row forever and freeze propagation for good."""
        event = self._reconstruct_safely(row)
        if event is not None:
            for handler in self._registry.spread_handlers_for(event):
                try:
                    await handler(event)
                except Exception:
                    log.warning("tailer.spread_handler_failed", kind=row["kind"])
        self._spread_cursor = row["id"]

    def _reconstruct(self, row: TrailRow) -> BusinessEvent | None:
        """Rebuild the typed event from a business_events row (its own fields + scoping columns)."""
        event_type = self._registry.event_class_for(row["kind"])
        if event_type is None:
            return None
        return event_type.from_payload(task_payload(row))

    def _reconstruct_safely(self, row: TrailRow) -> BusinessEvent | None:
        """:meth:`_reconstruct`, but a payload that no longer fits its event class yields ``None``
        instead of raising — the caller skips the row rather than stalling on it. The skip is not
        silent: a stored fact that no longer rebuilds (a field made required after the row was
        written, a hand-inserted payload) is a defect, so it is logged at ``exception`` level — the
        capture seam folds it into a console Issue — not swallowed as a mere warning."""
        try:
            return self._reconstruct(row)
        except Exception:
            log.exception("tailer.reconstruct_failed", kind=row["kind"], event_id=str(row["id"]))
            return None

    async def _fan_out(self, session: AsyncSession, row: TrailRow) -> None:
        event_type = self._registry.event_class_for(row["kind"])
        if event_type is None:
            # A kind with no registered class: we can route this fact to no one. This is *not* the
            # benign "known kind, nobody listens" no-op below — it means a fact was persisted that
            # the running process cannot even name, so surface it as a console Issue (fingerprint-
            # grouped: one kind is one issue, not one per row). The row is still marked dispatched
            # by the caller — the cursor must advance, we simply have nothing to deliver.
            self._capture_unroutable(row)
            return
        subs = self._registry.subscribers_for(event_type)
        if not subs:
            return  # known kind, nobody listens — a clean no-op, no fact is lost
        payload = task_payload(row)
        actor = row["user_id"]
        for sub in subs:
            await enqueue(session, sub.topic, payload, user_id=actor if sub.as_actor else None)

    @staticmethod
    def _capture_unroutable(row: TrailRow) -> None:
        """Log an unroutable fact at ``exception`` level so the capture seam records a console
        Issue. Raised-and-caught to give the capture fingerprint a live traceback; the caller marks
        the row dispatched regardless, so a fact we cannot route never wedges the cursor."""
        try:
            raise UnroutableFact(f"no event class registered for kind {row['kind']!r}")
        except UnroutableFact:
            log.exception("tailer.unroutable_fact", kind=row["kind"], event_id=str(row["id"]))

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
                while await self.tick():
                    pass  # drain all ready facts before waiting
            except Exception:
                log.warning("tailer.tick_failed")
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
            await asyncpg_conn.add_listener(NOTIFY_CHANNEL, self._on_notify)
            self._listen_conn = raw
        except Exception:
            # No LISTEN (e.g. DB down at boot) — the poll loop still delivers, just not instantly.
            log.warning("tailer.listen_failed")

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
