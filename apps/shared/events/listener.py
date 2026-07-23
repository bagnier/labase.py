"""The event listener — reads the persisted trail and runs both deliveries off it.

``emit`` only writes a ``BusinessEvent`` to the ``business_events`` log inside the request's
transaction (:func:`~apps.shared.events.store.persist_fact`). This listener reads that log, woken by
the trail's ``AFTER INSERT`` NOTIFY (poll as a net), and runs the two deliveries the producer no
longer does — so it never knows its consumers nor waits for them:

- **``on`` / async fan-out — exactly-once, cluster-wide.** Each tick claims un-dispatched rows with
  ``FOR UPDATE SKIP LOCKED`` and, in the same transaction, enqueues one task-queue row per
  registered ``bus.on`` consumer (read via :meth:`~apps.shared.events.bus.EventBus.subscribers_for`)
  and stamps ``dispatched_at``. No sequence-visibility gap, and N instances never double-fan a row.
- **``spread`` — per instance.** A settings reload must run on *every* process, so it cannot claim:
  each tick reads facts newer than this process's in-memory cursor whose kind has a ``spread``
  subscriber and runs those handlers in-process (idempotent, so a replay is harmless).
- **Reconstruct from the row.** Both paths rebuild the typed event from the row's ``kind`` via the
  :func:`~apps.shared.events.types.event_class_for` registry; the async dedup key is the row id.
"""

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events.bus import events
from apps.shared.events.repository import EventRepository
from apps.shared.events.types import BusinessEvent, event_class_for, reconstruct
from apps.shared.persistence.database import _user_engine, admin_session_factory
from apps.shared.queue import enqueue

log = structlog.get_logger("labase.shared.listener")

NOTIFY_CHANNEL = "business_event"


def _task_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the async-consumer task payload from a business_events row: the event's own fields
    plus the row id as the dedup ``event_id``. Drops the denormalized ``actor`` handle (not a
    field)."""
    payload = dict(row["payload"] or {})
    payload.pop("actor", None)
    payload["actor_id"] = str(row["user_id"]) if row["user_id"] else None
    payload["org_id"] = str(row["org_id"]) if row["org_id"] else None
    payload["entity_id"] = row["entity_id"]
    payload["event_id"] = row["id"]  # the stable dedup key (bigint)
    return payload


class EventListener:
    def __init__(
        self,
        interval_seconds: float,
        batch_size: int = 50,
        session_factory: Callable[[], AsyncSession] | None = None,
        bus: Any | None = None,
    ) -> None:
        # session_factory overrides the admin session (the API test driver injects its rolled-back
        # test connection, so the tailer sees the same uncommitted facts a request just wrote).
        self._interval = interval_seconds
        self._batch = batch_size
        self._session_factory = session_factory
        self._bus = bus or events  # read spread subscribers from here (a test may inject its own)
        self._spread_cursor: int | None = None  # per-instance high-water for spread delivery
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

    async def _read_spread(self, repo: EventRepository) -> list[dict[str, Any]]:
        """Facts newer than the spread cursor whose kind has a ``spread`` subscriber."""
        kinds = [k for t in self._bus._spread_subs if (k := getattr(t, "kind", ""))]
        if not kinds:
            return []
        cursor = self._spread_cursor if self._spread_cursor is not None else 0
        return await repo.scan_spread(cursor, kinds)

    async def _apply_spread(self, row: dict[str, Any]) -> None:
        """Reconstruct the fact and run its ``spread`` handlers on this instance, then advance the
        cursor. Handlers are idempotent (a reload is a plain assignment), so a failure is logged and
        skipped rather than blocking the cursor."""
        event = self._reconstruct(row)
        if event is not None:
            for handler in self._bus._handlers_for(event, self._bus._spread_subs, set()):
                try:
                    await handler(event)
                except Exception:
                    log.warning("tailer.spread_handler_failed", kind=row["kind"])
        self._spread_cursor = row["id"]

    def _reconstruct(self, row: dict[str, Any]) -> BusinessEvent | None:
        """Rebuild the typed event from a business_events row (its own fields + scoping columns)."""
        event_type = event_class_for(row["kind"])
        if event_type is None:
            return None
        return reconstruct(event_type, _task_payload(row))

    async def _fan_out(self, session: AsyncSession, row: dict[str, Any]) -> None:
        event_type = event_class_for(row["kind"])
        if event_type is None:
            return  # unknown kind (e.g. a legacy row) — nothing to deliver; still marked dispatched
        subs = self._bus.subscribers_for(event_type)
        if not subs:
            return
        payload = _task_payload(row)
        actor = row["user_id"]
        for sub in subs:
            await enqueue(session, sub.topic, payload, user_id=actor if sub.as_actor else None)

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
