"""One invariant over the *lifespan loops*: a loop that falls over is not a warning.

The five background workers all wrap their tick in ``except Exception`` — they have to, since one
bad tick must never end the loop. What that bought was silence: a task worker that stopped
claiming, or an event listener that stopped delivering, left nothing but a ``warning`` inside a
log window that rolls over in two days, so the console showed a healthy server while the
durable half of the event system was dead.

Three of the five now put that failure through the verdict in
``apps.shared.logs.loop`` — the transition into failure is a bug, the ticks after it are
the same outage, the recovery carries the toll. The other two are excluded *on purpose* and stay
at ``warning``: the log writer and the capture drain are the machinery the seam itself runs
on, so an ``exception`` from either would re-enter the queue it just failed to drain.

This lives in ``tests/meta`` for the reason ``test_event_vocabulary`` does: shared may not
import a bounded context, and one of the three loops is ``apps.metrics``'.
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

# ``(the loop's name, how to build one)`` — the name is what the verdict derives both of its
# event names from, so asserting it is asserting that each loop kept the line it always wrote.
# A factory rather than an instance: the health state *is* "has this loop been failing", so a
# worker shared between two tests would carry the first one's outage into the second.
_LOOPS = [
    ("queue.worker", lambda: TaskWorker(interval_seconds=0)),
    ("listener.tick", lambda: EventListener(interval_seconds=0)),
    ("metrics.flush", lambda: MetricsFlusher(interval_seconds=0)),
]


@pytest.mark.parametrize(("name", "build"), _LOOPS, ids=[name for name, _ in _LOOPS])
@pytest.mark.asyncio
async def test_a_lifespan_loop_that_falls_over_opens_an_issue(name, build, monkeypatch):
    """``error`` carrying a live exception *is* the capture seam — the one level that reaches the
    console. A worker nobody is retrying has no other way to be seen."""

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
    """The whole transition, on the worker rather than on ``LoopHealth`` alone: the first failing
    tick is the bug, the second is the same outage counted, and the tick that returns is what
    ends it — a worker that forgot to report its success would never recover, and its *next*
    outage would only warn."""
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


# All five loops this time, built on the session factory a test hands them — the two excluded
# from the verdict have no ``guarded_tick`` and are driven by their bare ``tick``.
_EVERY_LOOP: list[tuple[str, Callable[[Callable[[], AsyncSession]], object]]] = [
    ("queue.worker", lambda factory: TaskWorker(interval_seconds=0, session_factory=factory)),
    ("listener.tick", lambda factory: EventListener(interval_seconds=0, session_factory=factory)),
    ("metrics.flush", lambda _factory: MetricsFlusher(interval_seconds=0)),
    ("log_sink", lambda _factory: LogDrain(interval_seconds=0)),
    ("capture", lambda _factory: CaptureDrain(interval_seconds=0)),
]


@pytest_asyncio.fixture
async def at_rest(monkeypatch):
    """A server with nothing to do: a transaction on which no task is owed and no fact awaits
    dispatch, both in-process queues emptied, and every loop's session bound to that transaction
    — rolled back afterwards, so what a real tick does to an idle store is discarded, and what it
    would have found in a shared test database is not what this measures."""
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()
    conn = await begin_test_transaction(db._admin_engine())
    async with AsyncSession(bind=conn, expire_on_commit=False) as session:
        await session.execute(text("delete from task_queue"))
        await session.execute(
            text("update business_events set checked_at = now() where checked_at is null")
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
    """A line per successful tick is a line per second, per worker, forever — so the *real* tick
    runs here, on a store with nothing owed, and every loop takes its turn. Pinning the verdict
    wrapper alone would leave a ``log.warning`` inside the tick itself unseen."""
    worker = build(at_rest)
    tick = getattr(worker, "guarded_tick", worker.tick)

    with capture_logs() as logs:
        await tick()

    assert logs == []
