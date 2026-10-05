"""Durable task queue on Postgres (AGENTS: deferred work rides a durable Postgres queue).

A failing handler is retried after a fixed backoff up to ``max_attempts``, then parked
(``failed_at``, ``last_error``).

A task carrying ``user_id`` runs on an RLS session with that user's claims, so the policies decide
as for a request; one without runs on the admin session, an explicit choice for server-level work.

``ensure_scheduled`` plants a recurring topic's row at mount; each successful run enqueues the
next in the transaction that marks it done.
"""

import asyncio
import contextlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, TypedDict, cast

import structlog
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.logs.loop import LoopHealth
from apps.shared.persistence.database import _user_engine, admin_session_factory
from apps.shared.persistence.rls import clear_rls_context, set_rls_context

log = structlog.get_logger(__name__)

TaskHandler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]

_handlers: dict[str, TaskHandler] = {}

_RETRY_BACKOFF_SECONDS = 60
_VISIBILITY_TIMEOUT_SECONDS = 300  # a crashed worker's claim expires after this

# Set by ``events.repository.task_payload``; any task whose payload carries them is correlated.
_CORRELATION_KEYS = ("request_id", "event_id", "user_id", "org_id")


def delivery_context(payload: dict[str, Any]) -> dict[str, str]:
    """The correlation keys present in ``payload``, to bind on the task's logs."""
    return {key: str(payload[key]) for key in _CORRELATION_KEYS if payload.get(key) is not None}


# Done rows are receipts; only this purge deletes them.
QUEUE_PURGE_TOPIC = "task_queue.purge"
QUEUE_PURGE_EVERY_SECONDS = 86400
QUEUE_RETENTION_DAYS = 7


class UnhandledTopic(Exception):
    """A claimed task whose topic has no handler, e.g. a disabled app's recurring row. Raised and
    caught to open an issue; every orphaned topic folds into that one issue, the topic in each
    occurrence's context.
    """


class ClaimedTask(TypedDict):
    """``_CLAIM``'s ``RETURNING`` columns. ``payload`` may be a dict or its JSON string."""

    id: uuid.UUID
    topic: str
    payload: Any
    user_id: uuid.UUID | None
    recurring_seconds: int | None
    attempts: int
    max_attempts: int


def register_task_handler(topic: str, handler: TaskHandler) -> None:
    _handlers[topic] = handler


def reset_task_handlers() -> None:
    _handlers.clear()


async def enqueue(
    session: AsyncSession,
    topic: str,
    payload: dict[str, Any] | None = None,
    *,
    user_id: uuid.UUID | None = None,
    max_attempts: int = 5,
) -> None:
    """Insert a task on the caller's session: it exists iff that transaction commits."""
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
    """Plant a recurring topic's row at mount, unless it exists."""
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


async def purge_finished_tasks(session: AsyncSession, retention_days: int) -> int:
    """Delete done rows older than ``retention_days``; returns how many. Pending and parked rows
    are still owed something, whatever their age."""
    deleted = await session.scalar(
        text(
            "WITH purged AS ("
            "  DELETE FROM task_queue"
            "  WHERE done_at < now() - make_interval(days => :days) RETURNING 1"
            ") SELECT count(*) FROM purged"
        ),
        {"days": retention_days},
    )
    return int(deleted or 0)


# Derived, not stored: a status column would be a second truth to keep in step.
_STATE = (
    "CASE WHEN done_at IS NOT NULL THEN 'done' "
    "     WHEN failed_at IS NOT NULL THEN 'parked' "
    "     WHEN attempts > 0 THEN 'retrying' "
    "     ELSE 'pending' END"
)

# When a row landed, or is due.
_MOMENT = "coalesce(done_at, failed_at, run_at)"

TASK_STATES: tuple[str, ...] = ("parked", "retrying", "pending")


class TaskBucket(BaseModel):
    """The runs of one topic in one slot of time and state, counted in Postgres: a busy window
    holds tens of thousands of rows."""

    topic: str
    slot: datetime
    state: str
    runs: int
    recurring_seconds: int | None


# A ``timestamptz``, like the log sink's buckets it is joined with in Python.
_BUCKET_SLOT = "to_timestamp(floor(extract(epoch from {moment}) / :bucket) * :bucket)"


def _bucketed(moment: str, family: str) -> str:
    slot = _BUCKET_SLOT.format(moment=moment)
    return (
        f"SELECT topic, {slot} AS slot, {_STATE} AS state, count(*) AS runs, "
        "  max(recurring_seconds) AS recurring_seconds "
        "FROM task_queue "
        f"WHERE recurring_seconds IS {family} NULL "
        f"  AND {moment} BETWEEN :since AND :until "
        "GROUP BY topic, slot, state ORDER BY topic, slot"
    )


async def bucketed_runs(
    session: AsyncSession, *, since: datetime, until: datetime, bucket: int, recurring: bool
) -> list[TaskBucket]:
    rows = await session.execute(
        text(_bucketed(_MOMENT, "NOT" if recurring else "")),
        {"since": since, "until": until, "bucket": bucket},
    )
    return [TaskBucket.model_validate(dict(row)) for row in rows.mappings()]


class RecurringTopic(BaseModel):
    """A recurring topic's interval and next run. No fixed hour: the next run is scheduled from
    the end of the last, so it drifts."""

    every_seconds: int
    next_run: datetime


async def live_recurring_topics(session: AsyncSession) -> dict[str, RecurringTopic]:
    """Recurring topics with a pending row, regardless of any window: a lane missing on a quiet
    hour would read as a removed topic."""
    rows = await session.execute(
        text(
            "SELECT topic, max(recurring_seconds) AS every, min(run_at) AS next_run "
            "FROM task_queue "
            "WHERE recurring_seconds IS NOT NULL AND done_at IS NULL AND failed_at IS NULL "
            "GROUP BY topic ORDER BY topic"
        )
    )
    return {
        row.topic: RecurringTopic(every_seconds=int(row.every), next_run=row.next_run)
        for row in rows
    }


class QueuedTaskRead(BaseModel):
    """A task still owed, for the console. A hundred tasks failing alike are one issue but a
    hundred rows here."""

    id: uuid.UUID
    topic: str
    state: str
    attempts: int
    max_attempts: int
    run_at: datetime
    failed_at: datetime | None
    last_error: str | None
    payload: dict[str, Any]
    user_id: uuid.UUID | None
    recurring_seconds: int | None


async def list_unfinished_tasks(
    session: AsyncSession, *, state: str = "", topic: str = "", limit: int = 200
) -> list[QueuedTaskRead]:
    """Tasks still owed, parked first. ``topic`` matches a fragment of compound topics such as
    ``evt:auth.user_created:create_org``."""
    rows = await session.execute(
        text(
            f"SELECT id, topic, {_STATE} AS state, attempts, max_attempts, run_at, failed_at, "
            "  last_error, payload, user_id, recurring_seconds "
            "FROM task_queue "
            "WHERE done_at IS NULL "
            f"  AND (:state = '' OR {_STATE} = :state) "
            "  AND (:topic = '' OR topic ILIKE '%' || :topic || '%') "
            "ORDER BY failed_at DESC NULLS LAST, run_at DESC "
            "LIMIT :limit"
        ),
        {"state": state, "topic": topic, "limit": limit},
    )
    return [QueuedTaskRead.model_validate(dict(row)) for row in rows.mappings()]


async def unfinished_task_topics(session: AsyncSession) -> list[str]:
    """Topics of unfinished tasks, for the console's filter."""
    rows = await session.scalars(
        text("SELECT DISTINCT topic FROM task_queue WHERE done_at IS NULL ORDER BY topic")
    )
    return list(rows)


async def count_unfinished_tasks(session: AsyncSession) -> dict[str, int]:
    """Unfinished rows per state, zeroes included."""
    rows = await session.execute(
        text(
            f"SELECT {_STATE} AS state, count(*) AS n "
            "FROM task_queue WHERE done_at IS NULL GROUP BY 1"
        )
    )
    counted = {row.state: int(row.n) for row in rows}
    return {state: counted.get(state, 0) for state in TASK_STATES}


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

    ``session_factory`` replaces the admin sessions: the API test driver passes its rolled-back
    connection.
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
        self._health = LoopHealth(log, "queue.worker")

    def _admin_session(self) -> AsyncSession:
        factory = self._session_factory or admin_session_factory()
        return factory()

    async def _admin_exec(self, *statements: tuple[Any, dict[str, Any]]) -> None:
        """Run ``(sql, params)`` statements in one admin transaction."""
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

    async def guarded_tick(self) -> None:
        """Drain ready tasks and report the outcome to the loop verdict. Public so tests can
        drive the failure path."""
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
            await asyncio.sleep(self._interval)

    async def tick(self) -> int:
        """Claim and run one batch; returns its size."""
        async with self._admin_session() as session:
            rows = (await session.execute(_CLAIM, {"batch": self._batch})).mappings().all()
            await session.commit()
        for row in rows:
            await self._process(cast(ClaimedTask, dict(row)))
        return len(rows)

    async def _process(self, task: ClaimedTask) -> None:
        payload = _payload_dict(task)
        with structlog.contextvars.bound_contextvars(**delivery_context(payload)):
            handler = _handlers.get(task["topic"])
            if handler is None:
                self._report_unhandled_topic(task)
                await self._fail(task, "no handler registered")
                return
            try:
                await self._run_handler(handler, payload, task["user_id"])
            except Exception as exc:
                if task["attempts"] >= task["max_attempts"]:
                    # Final: an issue. ``str``, since capture keeps only scalar context.
                    log.exception(
                        "queue.task_failed",
                        exc_info=exc,
                        topic=task["topic"],
                        task_id=str(task["id"]),
                    )
                    await self._fail(task, repr(exc))
                else:
                    # A retry is not a bug yet: no issue per transient blip.
                    log.warning(
                        "queue.task_retrying",
                        topic=task["topic"],
                        task_id=str(task["id"]),
                        attempt=task["attempts"],
                        exc_info=exc,
                    )
                    await self._retry(task, repr(exc))
            else:
                # No line: ``done_at`` and the handler's facts already record it.
                await self._complete(task)

    async def _run_handler(
        self, handler: TaskHandler, payload: dict[str, Any], user_id: uuid.UUID | None
    ) -> None:
        if user_id is None:
            async with self._admin_session() as session:
                await handler(session, payload)
                await session.commit()
            return
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

    @staticmethod
    def _report_unhandled_topic(task: ClaimedTask) -> None:
        try:
            raise UnhandledTopic(f"no handler registered for topic {task['topic']!r}")
        except UnhandledTopic:
            log.exception("queue.unhandled_topic", topic=task["topic"], task_id=str(task["id"]))

    async def _fail(self, task: ClaimedTask, error: str) -> None:
        # No line: both callers just logged the failure as an exception.
        await self._admin_exec(
            (
                text(
                    "UPDATE task_queue SET failed_at = now(), locked_at = NULL, "
                    "last_error = :error WHERE id = :id"
                ),
                {"id": task["id"], "error": error},
            )
        )
