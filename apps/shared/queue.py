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

# The queue's own retention: done rows are receipts, and nothing else ever deletes them.
QUEUE_PURGE_TOPIC = "task_queue.purge"
QUEUE_PURGE_EVERY_SECONDS = 86400
QUEUE_RETENTION_DAYS = 7


class UnhandledTopic(Exception):
    """A claimed task whose topic no mount registered a handler for.

    Raised only to give the capture seam a live exception to fingerprint on — caught immediately
    and logged, exactly like the rate limiter's ``UnlimitedEndpoint`` and the listener's
    ``UnroutableFact``. Parking is as final as exhausting the retries, but this path never raised,
    so it left a bare ``log.error`` — precisely the level the seam ignores — and the hole rolled
    out of the log window with no issue ever opened. Disabling an app is enough to reach it: its
    recurring rows outlive the mount that used to answer them.

    The fingerprint is the exception type plus the frames, never the message, so every orphaned
    topic folds into *one* issue — the same trade ``UnroutableFact`` already makes. Which topic it
    was rides in the occurrence's context, where an admin reads it.
    """


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


async def purge_finished_tasks(session: AsyncSession, retention_days: int) -> int:
    """Retention consumer: drop done rows past the window; returns how many.

    Done rows only — a pending row is still owed a run and a parked one a triage, so age alone
    never removes those. Counted through a CTE, the shape ``purge_old_occurrences`` already uses.
    """
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


# What a row *is* to a reader, derived rather than stored: the columns already say it, and a
# status column would be a second truth for ``_retry``/``_fail`` to keep in step. ``done`` is
# excluded from every read below — a done row is a receipt, and there are a week of them.
_STATE = (
    "CASE WHEN done_at IS NOT NULL THEN 'done' "
    "     WHEN failed_at IS NOT NULL THEN 'parked' "
    "     WHEN attempts > 0 THEN 'retrying' "
    "     ELSE 'pending' END"
)

# What the history reads a row's moment as: when it landed, or when it is due if it has not.
_MOMENT = "coalesce(done_at, failed_at, run_at)"

TASK_STATES: tuple[str, ...] = ("parked", "retrying", "pending")


class TaskBucket(BaseModel):
    """Every run of one topic that landed in one slot of time, counted.

    Counted in Postgres rather than read out and grouped in Python: a busy window holds tens of
    thousands of rows, and the screen draws a few hundred blocks whatever it holds. Nothing is
    capped and nothing is dropped — what a bucket costs is the ability to point at one run, which
    the backlog screen and the log sink both still answer.
    """

    topic: str
    slot: datetime
    state: str
    runs: int
    recurring_seconds: int | None


# Left as ``timestamptz``: the log sink's own bucketing keys on the same aware instant, and the
# two are joined in Python on that key.
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
    """Every run in the window, folded into slots — one row per topic and slot, never per run."""
    rows = await session.execute(
        text(_bucketed(_MOMENT, "NOT" if recurring else "")),
        {"since": since, "until": until, "bucket": bucket},
    )
    return [TaskBucket.model_validate(dict(row)) for row in rows.mappings()]


async def live_recurring_topics(session: AsyncSession) -> dict[str, int]:
    """The recurring topics that still have a pending singleton, and how often each comes round.

    Read whatever the window holds: a recurring topic is a permanent fixture, and a lane that
    vanishes on a quiet hour reads as the topic having been removed.
    """
    rows = await session.execute(
        text(
            "SELECT topic, max(recurring_seconds) AS every FROM task_queue "
            "WHERE recurring_seconds IS NOT NULL AND done_at IS NULL AND failed_at IS NULL "
            "GROUP BY topic ORDER BY topic"
        )
    )
    return {row.topic: int(row.every) for row in rows}


class QueuedTaskRead(BaseModel):
    """One row of work the queue still owes, as the console reads it.

    Deliberately not an issue: a hundred tasks failing the same way fold into one issue and stay a
    hundred rows here, and resolving that issue runs none of them.
    """

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
    """The tasks still owed, parked first — the order an admin reads them in.

    ``topic`` matches a fragment, which is what makes the pivot off an issue work: the occurrence
    keeps the topic, and the queue's topics are compound (``evt:auth.user_created:create_org``).
    """
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
    """The topics actually present, for the console's filter to offer.

    A placeholder is a guess an admin has to already know the answer to; the list is what is
    there — the same trade the org-handle datalist makes on the settings screen.
    """
    rows = await session.scalars(
        text("SELECT DISTINCT topic FROM task_queue WHERE done_at IS NULL ORDER BY topic")
    )
    return list(rows)


async def count_unfinished_tasks(session: AsyncSession) -> dict[str, int]:
    """How many rows sit in each state — every state keyed, including the zeroes, so a caller
    never has to spell the absence itself."""
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
        self._health = LoopHealth(log, "queue.worker")

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

    async def guarded_tick(self) -> None:
        """One pass of the loop, and the verdict its outcome earns.

        Split out of ``_run`` so the failure path is drivable: a test cannot race an infinite
        loop, and a worker that stops claiming is exactly what used to go unnoticed.
        """
        try:
            while await self.tick():
                pass  # drain ready tasks before sleeping
        except Exception as exc:
            self._health.tick_failed(exc)
        else:
            self._health.tick_succeeded()

    async def _run(self) -> None:
        while True:
            await self.guarded_tick()
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
            self._report_unhandled_topic(task)
            await self._fail(task, "no handler registered")
            return
        payload = _payload_dict(task)
        try:
            await self._run_handler(handler, payload, task["user_id"])
        except Exception as exc:
            if task["attempts"] >= task["max_attempts"]:
                # Retries exhausted: nobody will run this task again, so the failure is final —
                # ``log.exception`` is the capture seam, and an issue is where it stays visible.
                # ``str`` is not cosmetic: the capture processor keeps only scalars, so a raw
                # ``UUID`` here reaches the log line and never the occurrence — leaving an issue
                # that names the topic but not the row still owed.
                log.exception(
                    "queue.task_failed", exc_info=exc, topic=task["topic"], task_id=str(task["id"])
                )
                await self._fail(task, repr(exc))
            else:
                # The queue's own retry is a lifecycle, not a defect: capturing here would open
                # an issue per transient blip, and close none when the next attempt succeeds.
                log.warning(
                    "queue.task_retrying",
                    topic=task["topic"],
                    task_id=str(task["id"]),
                    attempt=task["attempts"],
                    exc_info=exc,
                )
                await self._retry(task, repr(exc))
        else:
            # No receipt: a task that ran is already recorded, by ``done_at`` on its own row and by
            # whatever fact the handler emitted. A line per task is a line per second on a busy
            # queue, saying what two other stores say better.
            await self._complete(task)

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

    @staticmethod
    def _report_unhandled_topic(task: ClaimedTask) -> None:
        """Say that this topic has no handler, where an admin will still see it tomorrow."""
        try:
            raise UnhandledTopic(f"no handler registered for topic {task['topic']!r}")
        except UnhandledTopic:
            log.exception("queue.unhandled_topic", topic=task["topic"], task_id=str(task["id"]))

    async def _fail(self, task: ClaimedTask, error: str) -> None:
        # Silent on purpose: both callers have just written the failure at ``exception`` level —
        # ``queue.task_failed`` with the exception itself, ``queue.unhandled_topic`` with the
        # orphaned topic — so a line here would say a third time what the seam already captured.
        await self._admin_exec(
            (
                text(
                    "UPDATE task_queue SET failed_at = now(), locked_at = NULL, "
                    "last_error = :error WHERE id = :id"
                ),
                {"id": task["id"], "error": error},
            )
        )
