"""The async event tailer — durable, at-least-once fan-out of persisted business events.

``emit`` writes a ``BusinessEvent`` to the ``business_events`` log inside the request's transaction
(:func:`~apps.shared.events.store.persist_fact`). This tailer reads that log and,
per new fact, enqueues one task-queue row per registered async consumer
(:func:`~apps.shared.events.outbox` ``on_async``). The producer never knows its consumers and never
waits for them.

- **Claim, don't cursor.** Each tick claims un-dispatched rows with ``FOR UPDATE SKIP LOCKED`` and,
  in the same transaction, enqueues their tasks and stamps ``dispatched_at``. No sequence-visibility
  gap, and N instances never double-fan a row.
- **Wake on NOTIFY, poll as a net.** An ``AFTER INSERT`` trigger ``pg_notify``s on commit, so
  delivery is ~immediate; the poll loop is the durability net (NOTIFY is lost with no listener).
- **Reconstruct from the row.** The consumer receives the typed event, rebuilt from the row via the
  ``kind`` → class registry (:func:`~apps.shared.events.event_class_for`); the dedup key is the id.
"""

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events.outbox import subscribers_for
from apps.shared.events.types import event_class_for
from apps.shared.persistence.database import _user_engine, admin_session_factory
from apps.shared.queue import enqueue

log = structlog.get_logger("labase.shared.tailer")

NOTIFY_CHANNEL = "business_event"

# Claim a batch of never-dispatched facts, oldest first, skipping rows another tailer holds.
_CLAIM = text(
    "SELECT id, kind, level, icon, user_id, org_id, entity_id, payload "
    "FROM business_events "
    "WHERE dispatched_at IS NULL "
    "ORDER BY id "
    "FOR UPDATE SKIP LOCKED "
    "LIMIT :batch"
)


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


class EventTailer:
    def __init__(
        self,
        interval_seconds: float,
        batch_size: int = 50,
        session_factory: Callable[[], AsyncSession] | None = None,
    ) -> None:
        # session_factory overrides the admin session (the API test driver injects its rolled-back
        # test connection, so the tailer sees the same uncommitted facts a request just wrote).
        self._interval = interval_seconds
        self._batch = batch_size
        self._session_factory = session_factory
        self._task: asyncio.Task | None = None
        self._listen_conn: Any | None = None
        self._wake = asyncio.Event()

    def _session(self) -> AsyncSession:
        factory = self._session_factory or admin_session_factory()
        return factory()

    async def tick(self) -> int:
        """Claim one batch of facts, fan each out to its consumers, stamp them dispatched. Returns
        how many were dispatched. One transaction: the tasks and the mark commit together."""
        async with self._session() as session:
            claimed = await session.execute(_CLAIM, {"batch": self._batch})
            rows = [dict(r) for r in claimed.mappings()]
            for row in rows:
                await self._fan_out(session, row)
            if rows:
                await session.execute(
                    text("UPDATE business_events SET dispatched_at = now() WHERE id = ANY(:ids)"),
                    {"ids": [r["id"] for r in rows]},
                )
            await session.commit()
        return len(rows)

    async def _fan_out(self, session: AsyncSession, row: dict[str, Any]) -> None:
        event_type = event_class_for(row["kind"])
        if event_type is None:
            return  # unknown kind (e.g. a legacy row) — nothing to deliver; still marked dispatched
        subs = subscribers_for(event_type)
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
