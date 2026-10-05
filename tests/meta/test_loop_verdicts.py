"""The lifespan loops report through the loop verdict (AGENTS: a failure that repeats is one
bug), but the log drain and the capture drain, which warn: an exception would re-enter their own
queues. Here because one loop is ``apps.metrics``'.
"""

from collections.abc import Callable

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from apps.metrics.infra import flusher as flusher_module
from apps.metrics.infra.flusher import MetricsFlusher
from apps.shared.events.listener import EventListener
from apps.shared.logs import capture, sink
from apps.shared.logs.capture import CaptureDrain
from apps.shared.logs.sink import LogDrain
from apps.shared.persistence import database as db
from apps.shared.queue import TaskWorker
from tests.e2e.drivers.api_transaction import begin_test_transaction, end_test_transaction

# ``(loop name, factory)``: a fresh worker per test, since it carries its outage state.
_LOOPS = [
    ("queue.worker", lambda: TaskWorker(interval_seconds=0)),
    ("listener.tick", lambda: EventListener(interval_seconds=0)),
    ("metrics.flush", lambda: MetricsFlusher(interval_seconds=0)),
]


@pytest.mark.parametrize(("name", "build"), _LOOPS, ids=[name for name, _ in _LOOPS])
@pytest.mark.asyncio
async def test_a_lifespan_loop_that_falls_over_opens_an_issue(name, build, monkeypatch):

    async def broken(*_args, **_kwargs):
        raise RuntimeError("the loop's own query blew up")

    worker = build()
    monkeypatch.setattr(worker, "tick", broken)

    with capture_logs() as logs:
        await worker.guarded_tick()

    assert [(entry["event"], entry["log_level"]) for entry in logs] == [(f"{name}_failed", "error")]


@pytest.mark.parametrize(("name", "build"), _LOOPS, ids=[name for name, _ in _LOOPS])
@pytest.mark.asyncio
async def test_a_loop_that_comes_back_says_what_the_outage_cost(name, build, monkeypatch):
    """On the worker itself: one forgetting to report success would never recover."""
    outcomes = iter([RuntimeError("down"), RuntimeError("still down"), None])

    async def flapping(*_args, **_kwargs):
        outcome = next(outcomes)
        if outcome is not None:
            raise outcome
        return 0

    worker = build()
    monkeypatch.setattr(worker, "tick", flapping)

    with capture_logs() as logs:
        for _ in range(3):
            await worker.guarded_tick()

    assert [(entry["event"], entry["log_level"], entry.get("failures")) for entry in logs] == [
        (f"{name}_failed", "error", None),
        (f"{name}_failed", "warning", 2),
        (f"{name}_recovered", "info", 2),
    ]


# All five loops; the two without ``guarded_tick`` run their ``tick``.
_EVERY_LOOP: list[tuple[str, Callable[[Callable[[], AsyncSession]], object]]] = [
    ("queue.worker", lambda factory: TaskWorker(interval_seconds=0, session_factory=factory)),
    ("listener.tick", lambda factory: EventListener(interval_seconds=0, session_factory=factory)),
    ("metrics.flush", lambda _factory: MetricsFlusher(interval_seconds=0)),
    ("log_sink", lambda _factory: LogDrain(interval_seconds=0)),
    ("capture", lambda _factory: CaptureDrain(interval_seconds=0)),
]


@pytest_asyncio.fixture
async def at_rest(monkeypatch):
    """An idle server: nothing owed or undispatched, queues empty, all in one rolled-back
    transaction."""
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()
    conn = await begin_test_transaction(db._admin_engine())
    async with AsyncSession(bind=conn, expire_on_commit=False) as session:
        await session.execute(text("delete from task_queue"))
        await session.execute(
            text("update business_events set dispatched_at = now() where dispatched_at is null")
        )
        await session.commit()

    def factory() -> AsyncSession:
        return AsyncSession(bind=conn, expire_on_commit=False)

    monkeypatch.setattr(flusher_module, "admin_session_factory", lambda: factory)
    monkeypatch.setattr(sink, "admin_session_factory", lambda: factory)
    sink._QUEUE.clear()
    sink._overflow.dropped = 0
    capture._QUEUE.clear()
    capture._overflow.dropped = 0

    yield factory

    await end_test_transaction(conn)
    await db._admin_engine().dispose()
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


@pytest.mark.parametrize(("name", "build"), _EVERY_LOOP, ids=[name for name, _ in _EVERY_LOOP])
@pytest.mark.asyncio
async def test_a_healthy_lifespan_loop_writes_nothing(name, build, at_rest):
    """The real ticks, so a line inside a tick is seen too."""
    worker = build(at_rest)
    tick = getattr(worker, "guarded_tick", worker.tick)

    with capture_logs() as logs:
        await tick()

    assert logs == []
