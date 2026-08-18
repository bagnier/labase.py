"""Durable task queue on Postgres — the async substrate.

`enqueue` writes through the caller's session, so a task exists iff the business
transaction commits (outbox semantics). A per-process `TaskWorker` lifespan task
polls with ``FOR UPDATE SKIP LOCKED``: N instances share the table and never
double-claim. A failing handler retries with linear backoff until
``max_attempts``, then parks as failed (``failed_at``/``last_error``) for
inspection.

Background RLS convention: a task carrying ``user_id`` runs its handler on an
RLS session with synthesized claims (``{"sub": user_id, "role": "authenticated"}``
via ``set_config``) — the policies decide, exactly as for a request. Tasks
without ``user_id`` run on the admin session: server-level work, an explicit
choice, never a blanket BYPASSRLS for tenant data.

Recurring work: ``ensure_scheduled(topic, every_seconds)`` at mount registers a
singleton row; on success the worker re-enqueues the next run in the same
transaction that marks the current one done.
"""

import asyncio
import contextlib
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict, cast

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.persistence.database import _user_engine, admin_session_factory
from apps.shared.persistence.rls import clear_rls_context, set_rls_context

log = structlog.get_logger("labase.shared.queue")

TaskHandler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]

_handlers: dict[str, TaskHandler] = {}

_RETRY_BACKOFF_SECONDS = 60
_VISIBILITY_TIMEOUT_SECONDS = 300  # a crashed worker's claim expires after this


class ClaimedTask(TypedDict):
    """A claimed ``task_queue`` row — exactly ``_CLAIM``'s ``RETURNING`` columns. ``payload`` is
    left ``Any``: the jsonb decodes to a dict, but a replayed row can arrive as its JSON string,
    which ``_payload_dict`` normalizes."""

    id: uuid.UUID
    topic: str
    payload: Any
    user_id: uuid.UUID | None
    recurring_seconds: int | None
    attempts: int
    max_attempts: int


def register_task_handler(topic: str, handler: TaskHandler) -> None:
    """Bind `topic` to `handler` — called from mount(), like event-bus subscriptions."""
    _handlers[topic] = handler


def reset_task_handlers() -> None:
    """Clear the registry — for test isolation."""
    _handlers.clear()


async def enqueue(
    session: AsyncSession,
    topic: str,
    payload: dict[str, Any] | None = None,
    *,
    user_id: uuid.UUID | None = None,
    max_attempts: int = 5,
) -> None:
    """Insert a task through the caller's session — commits with its transaction."""
    await session.execute(
        text(
            "INSERT INTO task_queue (topic, payload, user_id, max_attempts) "
            "VALUES (:topic, CAST(:payload AS jsonb), :user_id, :max_attempts)"
        ),
        {
            "topic": topic,
            "payload": json.dumps(payload or {}),
            "user_id": str(user_id) if user_id else None,
            "max_attempts": max_attempts,
        },
    )


async def ensure_scheduled(topic: str, every_seconds: int) -> None:
    """Idempotently plant the singleton row of a recurring topic (mount-time)."""
    async with admin_session_factory()() as session:
        await session.execute(
            text(
                "INSERT INTO task_queue (topic, recurring_seconds) "
                "VALUES (:topic, :every) "
                "ON CONFLICT DO NOTHING"
            ),
            {"topic": topic, "every": every_seconds},
        )
        await session.commit()


def _payload_dict(task: ClaimedTask) -> dict[str, Any]:
    payload = task["payload"]
    return payload if isinstance(payload, dict) else json.loads(payload)


_CLAIM = text(
    "UPDATE task_queue SET locked_at = now(), attempts = attempts + 1 "
    "WHERE id IN ("
    "  SELECT id FROM task_queue"
    "  WHERE done_at IS NULL AND failed_at IS NULL AND run_at <= now()"
    "    AND (locked_at IS NULL"
    f"         OR locked_at < now() - interval '{_VISIBILITY_TIMEOUT_SECONDS} seconds')"
    "  ORDER BY run_at"
    "  FOR UPDATE SKIP LOCKED"
    "  LIMIT :batch"
    ") "
    "RETURNING id, topic, payload, user_id, recurring_seconds, attempts, max_attempts"
)


class TaskWorker:
    """The per-process claimer, ticking on its own task.

    ``session_factory`` overrides the admin sessions it uses (claim, bookkeeping, admin handlers):
    the API test driver injects its rolled-back test connection, so drained tasks see — and leave —
    no committed rows.
    """

    def __init__(
        self,
        interval_seconds: float,
        batch_size: int = 10,
        session_factory: Callable[[], AsyncSession] | None = None,
    ) -> None:
        self._interval = interval_seconds
        self._batch = batch_size
        self._session_factory = session_factory
        self._task: asyncio.Task | None = None

    def _admin_session(self) -> AsyncSession:
        factory = self._session_factory or admin_session_factory()
        return factory()

    async def _admin_exec(self, *statements: tuple[Any, dict[str, Any]]) -> None:
        """Run one or more (sql, params) statements in a single admin transaction — the
        bookkeeping shape shared by ``_complete``/``_retry``/``_fail``."""
        async with self._admin_session() as session:
            for sql, params in statements:
                await session.execute(sql, params)
            await session.commit()

    async def start(self) -> None:
        if self._interval > 0 and self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                while await self.tick():
                    pass  # drain ready tasks before sleeping
            except Exception:
                log.warning("queue.worker_failed")
            await asyncio.sleep(self._interval)

    async def tick(self) -> int:
        """Claim and run one batch; returns how many tasks were processed."""
        async with self._admin_session() as session:
            rows = (await session.execute(_CLAIM, {"batch": self._batch})).mappings().all()
            await session.commit()
        for row in rows:
            await self._process(cast(ClaimedTask, dict(row)))
        return len(rows)

    async def _process(self, task: ClaimedTask) -> None:
        handler = _handlers.get(task["topic"])
        if handler is None:
            await self._fail(task, "no handler registered")
            return
        payload = _payload_dict(task)
        try:
            await self._run_handler(handler, payload, task["user_id"])
        except Exception as exc:
            log.exception("queue.task_failed", topic=task["topic"], task_id=task["id"])
            if task["attempts"] >= task["max_attempts"]:
                await self._fail(task, repr(exc))
            else:
                await self._retry(task, repr(exc))
        else:
            await self._complete(task)
            log.info("queue.task_done", topic=task["topic"], task_id=task["id"])

    async def _run_handler(
        self, handler: TaskHandler, payload: dict[str, Any], user_id: uuid.UUID | None
    ) -> None:
        if user_id is None:
            async with self._admin_session() as session:
                await handler(session, payload)
                await session.commit()
            return
        # RLS convention: synthesized tenant claims on a user-role connection.
        async with AsyncSession(_user_engine(), expire_on_commit=False) as session:
            await set_rls_context(session, {"sub": str(user_id), "role": "authenticated"})
            try:
                await handler(session, payload)
                await session.commit()
            finally:
                await clear_rls_context(session)

    async def _complete(self, task: ClaimedTask) -> None:
        statements: list[tuple[Any, dict[str, Any]]] = [
            (
                text("UPDATE task_queue SET done_at = now(), locked_at = NULL WHERE id = :id"),
                {"id": task["id"]},
            )
        ]
        if task["recurring_seconds"]:
            statements.append(
                (
                    text(
                        "INSERT INTO task_queue (topic, payload, user_id, recurring_seconds, "
                        "  max_attempts, run_at) "
                        "VALUES (:topic, CAST(:payload AS jsonb), :user_id, "
                        "  CAST(:every AS integer), :max_attempts, "
                        "  now() + make_interval(secs => CAST(:every AS double precision)))"
                    ),
                    {
                        "topic": task["topic"],
                        "payload": json.dumps(_payload_dict(task)),
                        "user_id": str(task["user_id"]) if task["user_id"] else None,
                        "every": task["recurring_seconds"],
                        "max_attempts": task["max_attempts"],
                    },
                )
            )
        await self._admin_exec(*statements)

    async def _retry(self, task: ClaimedTask, error: str) -> None:
        await self._admin_exec(
            (
                text(
                    "UPDATE task_queue SET locked_at = NULL, last_error = :error, "
                    "run_at = now() + make_interval(secs => :backoff) WHERE id = :id"
                ),
                {"id": task["id"], "error": error, "backoff": _RETRY_BACKOFF_SECONDS},
            )
        )

    async def _fail(self, task: ClaimedTask, error: str) -> None:
        log.error("queue.task_parked", topic=task["topic"], task_id=task["id"], error=error)
        await self._admin_exec(
            (
                text(
                    "UPDATE task_queue SET failed_at = now(), locked_at = NULL, "
                    "last_error = :error WHERE id = :id"
                ),
                {"id": task["id"], "error": error},
            )
        )
