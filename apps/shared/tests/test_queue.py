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
    """Fresh engines per test (loop binding) and a clean handler registry/table.

    The whole table is emptied up front: a prior in-process E2E server may have
    planted recurring singletons in the (disposable) test schema, and a tick
    running with a reset registry would claim and park them mid-test.

    The registry is snapshotted and restored (not just cleared): apps.main — imported by the
    e2e drivers — registers the real task handlers at mount, and a later e2e test relies on them
    still being there. Clearing without restoring would silently unregister the app's consumers.
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

    assert await worker.tick() == 1  # attempt 1 → retry scheduled with backoff
    first = await _row(topic)
    assert first["failed_at"] is None
    assert first["attempts"] == 1
    assert "boom" in first["last_error"]

    async with db.admin_session_factory()() as session:  # make it claimable again now
        await session.execute(
            text("UPDATE task_queue SET run_at = now() WHERE topic = :topic"), {"topic": topic}
        )
        await session.commit()

    assert await worker.tick() == 1  # attempt 2 = max_attempts → parked
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

    assert observed["role"] == "authenticated"
    assert str(user_id) in observed["claims"]


@pytest.mark.asyncio
async def test_recurring_task_reenqueues_next_run():
    topic = f"test.recurring_{uuid.uuid4().hex}"
    runs: list[dict] = []

    async def handler(session, payload):
        runs.append(payload)

    register_task_handler(topic, handler)
    await ensure_scheduled(topic, every_seconds=3600)
    await ensure_scheduled(topic, every_seconds=3600)  # idempotent

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
    """A done row is a receipt, not work — and nothing ever deleted them: a dev database grew
    65k of them in two weeks. Pending and parked rows are still owed something (a run, a triage),
    so age alone never removes those."""
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
    """A retry is the queue's own lifecycle, not a defect: capturing it opens an issue on every
    transient blip, and nothing closes that issue when the very next attempt succeeds."""
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
    """A task nobody registered a handler for parks on its very first claim, and parking is as
    final as exhausting the retries — but this path never raised, so it left a bare ``log.error``,
    which is precisely the level the capture seam ignores. Disabling an app is enough to reach it:
    its recurring rows outlive the mount that used to answer them."""
    topic = f"test.orphan_{uuid.uuid4().hex}"
    await _enqueue_committed(topic)
    capture._QUEUE.clear()

    await TaskWorker(interval_seconds=1).tick()

    assert [type(captured.exc).__name__ for captured in capture._QUEUE] == ["UnhandledTopic"]


@pytest.mark.asyncio
async def test_a_task_parked_for_good_is_captured_as_a_bug(log_chain):
    """Retries exhausted — nobody will ever run this task again, so the failure is final and an
    issue is the only place it still shows up."""
    topic = f"test.parked_{uuid.uuid4().hex}"

    async def handler(session, payload):
        raise RuntimeError("boom")

    register_task_handler(topic, handler)
    await _enqueue_committed(topic, max_attempts=1)
    capture._QUEUE.clear()

    await TaskWorker(interval_seconds=1).tick()

    assert [type(captured.exc) for captured in capture._QUEUE] == [RuntimeError]


@pytest.mark.asyncio
async def test_a_parked_task_names_itself_in_the_issue_it_opens(log_chain):
    """The pivot off the issue and back to the row that is still owed.

    ``task_id`` rode the line as a ``uuid.UUID``, and the capture processor keeps only scalars —
    so the occurrence carried the topic and lost the one value that identifies *which* task. The
    log line kept it (its payload encodes with ``default=str``), which is what made the gap read
    like a rendering detail rather than a broken pivot.
    """
    topic = f"test.parked_{uuid.uuid4().hex}"

    async def handler(session, payload):
        raise RuntimeError("boom")

    register_task_handler(topic, handler)
    await _enqueue_committed(topic, max_attempts=1)
    capture._QUEUE.clear()

    await TaskWorker(interval_seconds=1).tick()

    parked = await _row(topic)
    assert [c.context.get("task_id") for c in capture._QUEUE] == [str(parked["id"])]
