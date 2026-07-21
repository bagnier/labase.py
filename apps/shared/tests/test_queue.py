import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from apps.shared.persistence import database as db
from apps.shared.queue import (
    TaskWorker,
    _handlers,
    enqueue,
    ensure_scheduled,
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
                        "SELECT attempts, done_at, failed_at, last_error, run_at "
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
    user_id = uuid.uuid4()
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
