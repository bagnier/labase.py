import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from apps.shared.logs import capture
from apps.shared.persistence import database as db
from apps.shared.queue import (
    TaskWorker,
    _handlers,
    enqueue,
    ensure_scheduled,
    purge_finished_tasks,
    register_task_handler,
    reset_task_handlers,
)


def _clear_engine_caches() -> None:
    db._user_engine.cache_clear()
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


@pytest_asyncio.fixture(autouse=True)
async def queue_isolation():
    """Fresh engines, an empty table and handler registry, restored afterwards.

    The table is emptied up front: an earlier e2e server may have planted recurring rows that a
    tick would claim and park. The registry is restored, not just cleared: later e2e tests need
    the handlers ``apps.main`` registered.
    """
    _clear_engine_caches()
    saved_handlers = dict(_handlers)
    reset_task_handlers()
    async with db.admin_session_factory()() as session:
        await session.execute(text("DELETE FROM task_queue"))
        await session.commit()
    yield
    async with db.admin_session_factory()() as session:
        await session.execute(text("DELETE FROM task_queue WHERE topic LIKE 'test.%'"))
        await session.commit()
    _handlers.clear()
    _handlers.update(saved_handlers)
    await db._user_engine().dispose()
    await db._admin_engine().dispose()
    _clear_engine_caches()


async def _enqueue_committed(topic: str, payload: dict | None = None, **kwargs) -> None:
    async with db.admin_session_factory()() as session:
        await enqueue(session, topic, payload, **kwargs)
        await session.commit()


async def _row(topic: str) -> dict:
    async with db.admin_session_factory()() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT id, attempts, done_at, failed_at, last_error, run_at "
                        "FROM task_queue WHERE topic = :topic ORDER BY id DESC LIMIT 1"
                    ),
                    {"topic": topic},
                )
            )
            .mappings()
            .one()
        )
        return dict(row)


@pytest.mark.asyncio
async def test_a_task_rolls_back_with_the_transaction_that_enqueued_it():
    topic = f"test.outbox_{uuid.uuid4().hex}"

    async with db.admin_session_factory()() as session:
        await enqueue(session, topic, {"n": 1})
        await session.rollback()

    async with db.admin_session_factory()() as session:
        remaining = await session.scalar(
            text("SELECT count(*) FROM task_queue WHERE topic = :topic"), {"topic": topic}
        )
    assert remaining == 0


@pytest.mark.asyncio
async def test_worker_runs_enqueued_task():
    topic = f"test.ok_{uuid.uuid4().hex}"
    seen: list[dict] = []

    async def handler(session, payload):
        seen.append(payload)

    register_task_handler(topic, handler)
    await _enqueue_committed(topic, {"n": 1})
    processed = await TaskWorker(interval_seconds=1).tick()

    assert processed == 1
    assert seen == [{"n": 1}]
    assert (await _row(topic))["done_at"] is not None


@pytest.mark.asyncio
async def test_failing_task_retries_then_parks():
    topic = f"test.boom_{uuid.uuid4().hex}"

    async def handler(session, payload):
        raise RuntimeError("boom")

    register_task_handler(topic, handler)
    await _enqueue_committed(topic, max_attempts=2)
    worker = TaskWorker(interval_seconds=1)

    assert await worker.tick() == 1  # attempt 1: retry scheduled
    first = await _row(topic)
    assert first["failed_at"] is None
    assert first["attempts"] == 1
    assert "boom" in first["last_error"]

    async with db.admin_session_factory()() as session:  # skip the backoff
        await session.execute(
            text("UPDATE task_queue SET run_at = now() WHERE topic = :topic"), {"topic": topic}
        )
        await session.commit()

    assert await worker.tick() == 1  # attempt 2 = max_attempts: parked
    assert (await _row(topic))["failed_at"] is not None


@pytest.mark.asyncio
async def test_task_without_handler_parks():
    topic = f"test.orphan_{uuid.uuid4().hex}"
    await _enqueue_committed(topic)
    await TaskWorker(interval_seconds=1).tick()
    row = await _row(topic)
    assert row["failed_at"] is not None
    assert "no handler" in row["last_error"]


@pytest.mark.asyncio
async def test_task_with_user_id_runs_under_synthesized_rls_claims():
    topic = f"test.rls_{uuid.uuid4().hex}"
    user_id = uuid.uuid7()
    observed: dict = {}

    async def handler(session, payload):
        observed["role"] = await session.scalar(text("SELECT current_user"))
        observed["claims"] = await session.scalar(
            text("SELECT current_setting('request.jwt.claims', true)")
        )

    register_task_handler(topic, handler)
    await _enqueue_committed(topic, user_id=user_id)
    await TaskWorker(interval_seconds=1).tick()

    assert observed["role"] == "app_rls"
    assert str(user_id) in observed["claims"]


@pytest.mark.asyncio
async def test_recurring_task_reenqueues_next_run():
    topic = f"test.recurring_{uuid.uuid4().hex}"
    runs: list[dict] = []

    async def handler(session, payload):
        runs.append(payload)

    register_task_handler(topic, handler)
    await ensure_scheduled(topic, every_seconds=3600)
    await ensure_scheduled(topic, every_seconds=3600)

    assert await TaskWorker(interval_seconds=1).tick() == 1
    assert len(runs) == 1

    async with db.admin_session_factory()() as session:
        pending = await session.scalar(
            text(
                "SELECT count(*) FROM task_queue "
                "WHERE topic = :topic AND done_at IS NULL AND failed_at IS NULL "
                "AND run_at > now()"
            ),
            {"topic": topic},
        )
    assert pending == 1


@pytest.mark.asyncio
async def test_purge_drops_only_finished_tasks_past_retention():
    """Pending and parked rows are still owed something, whatever their age."""
    async with db.admin_session_factory()() as session:
        await session.execute(
            text(
                "INSERT INTO task_queue (topic, done_at, failed_at) VALUES "
                "('test.purge.old_done', now() - interval '8 days', NULL), "
                "('test.purge.fresh_done', now() - interval '6 days', NULL), "
                "('test.purge.old_parked', NULL, now() - interval '8 days'), "
                "('test.purge.pending', NULL, NULL)"
            )
        )
        await session.commit()

    async with db.admin_session_factory()() as session:
        deleted = await purge_finished_tasks(session, retention_days=7)
        await session.commit()

    async with db.admin_session_factory()() as session:
        topics = await session.scalars(text("SELECT topic FROM task_queue ORDER BY topic"))
        survivors = list(topics)
    assert (deleted, survivors) == (
        1,
        ["test.purge.fresh_done", "test.purge.old_parked", "test.purge.pending"],
    )


@pytest.mark.asyncio
async def test_a_failure_the_queue_will_retry_is_not_captured_as_a_bug(log_chain):
    topic = f"test.retry_{uuid.uuid4().hex}"

    async def handler(session, payload):
        raise RuntimeError("boom")

    register_task_handler(topic, handler)
    await _enqueue_committed(topic, max_attempts=2)
    capture._QUEUE.clear()

    await TaskWorker(interval_seconds=1).tick()

    assert list(capture._QUEUE) == []


@pytest.mark.asyncio
async def test_a_topic_no_mount_handles_is_captured_as_a_bug(log_chain):
    """It parks on its first claim, as final as exhausted retries (a disabled app's recurring
    rows)."""
    topic = f"test.orphan_{uuid.uuid4().hex}"
    await _enqueue_committed(topic)
    capture._QUEUE.clear()

    await TaskWorker(interval_seconds=1).tick()

    assert [type(captured.exc).__name__ for captured in capture._QUEUE] == ["UnhandledTopic"]


@pytest.mark.asyncio
async def test_an_unhandled_topic_carries_its_delivery_context_in_the_issue_it_opens(log_chain):
    """The binding starts before the handler lookup, since no handler runs here."""
    topic = f"test.orphan_ctx_{uuid.uuid4().hex}"
    request_id, event_id, user_id, org_id = (uuid.uuid7() for _ in range(4))
    await _enqueue_committed(
        topic,
        {
            "request_id": str(request_id),
            "event_id": str(event_id),
            "user_id": str(user_id),
            "org_id": str(org_id),
        },
    )
    capture._QUEUE.clear()

    await TaskWorker(interval_seconds=1).tick()

    context = capture._QUEUE[0].context
    assert (
        context["request_id"],
        context["event_id"],
        context["user_id"],
        context["org_id"],
    ) == (str(request_id), str(event_id), str(user_id), str(org_id))


@pytest.mark.asyncio
async def test_a_task_parked_for_good_is_captured_as_a_bug(log_chain):
    topic = f"test.parked_{uuid.uuid4().hex}"

    async def handler(session, payload):
        raise RuntimeError("boom")

    register_task_handler(topic, handler)
    await _enqueue_committed(topic, max_attempts=1)
    capture._QUEUE.clear()

    await TaskWorker(interval_seconds=1).tick()

    assert [type(captured.exc) for captured in capture._QUEUE] == [RuntimeError]


@pytest.mark.asyncio
async def test_a_parked_task_carries_its_delivery_context_in_the_issue_it_opens(log_chain):
    """``request_id``, ``event_id``, ``user_id`` and ``org_id``, read off the payload: the
    failure is logged outside the handler's own binding."""
    topic = f"test.parked_ctx_{uuid.uuid4().hex}"
    request_id, event_id, user_id, org_id = (uuid.uuid7() for _ in range(4))

    async def handler(session, payload):
        raise RuntimeError("boom")

    register_task_handler(topic, handler)
    await _enqueue_committed(
        topic,
        {
            "request_id": str(request_id),
            "event_id": str(event_id),
            "user_id": str(user_id),
            "org_id": str(org_id),
        },
        max_attempts=1,
    )
    capture._QUEUE.clear()

    await TaskWorker(interval_seconds=1).tick()

    context = capture._QUEUE[0].context
    assert (
        context["request_id"],
        context["event_id"],
        context["user_id"],
        context["org_id"],
    ) == (str(request_id), str(event_id), str(user_id), str(org_id))


@pytest.mark.asyncio
async def test_a_parked_task_names_itself_in_the_issue_it_opens(log_chain):
    """``task_id`` as a string: capture keeps only scalar context, and the admin needs the row."""
    topic = f"test.parked_{uuid.uuid4().hex}"

    async def handler(session, payload):
        raise RuntimeError("boom")

    register_task_handler(topic, handler)
    await _enqueue_committed(topic, max_attempts=1)
    capture._QUEUE.clear()

    await TaskWorker(interval_seconds=1).tick()

    parked = await _row(topic)
    assert [c.context.get("task_id") for c in capture._QUEUE] == [str(parked["id"])]
