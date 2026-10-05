"""The event listener — reads the journal and fans each fact to its async consumers."""

import uuid
from dataclasses import dataclass

import pytest
import pytest_asyncio
import structlog
from sqlalchemy import text
from structlog.testing import capture_logs

from apps.shared.events import BusinessEvent
from apps.shared.events.bus import EventBus, events
from apps.shared.events.listener import EventListener
from apps.shared.events.models import BusinessEventRecord
from apps.shared.events.wiring import EventWiring, wiring
from apps.shared.persistence import database as db
from apps.shared.queue import TaskWorker, _handlers
from apps.shared.tests.journal_seed import seed_fact, seed_fact_on


@dataclass(frozen=True, kw_only=True)
class _TailEvent(BusinessEvent):
    app_name = "test_listener"
    verb = "happened"
    label: str | None = None


class _TailEventSub(_TailEvent):
    """A concrete subclass of a concrete (kinded) event — its own kind, distinct from its base's,
    the shape a subscriber on the base must still reach (mirrors ``consumers_of``'s MRO walk)."""

    verb = "happened_sub"


@dataclass(frozen=True, kw_only=True)
class _SpreadEvent(BusinessEvent):
    app_name = "test_listener"
    verb = "spread"
    value: str | None = None


@dataclass(frozen=True, kw_only=True)
class _StrictSpreadEvent(BusinessEvent):
    """A stored fact missing ``value`` cannot rebuild."""

    app_name = "test_listener"
    verb = "strict_spread"
    value: str


def _clear_engine_caches() -> None:
    db._user_engine.cache_clear()
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


async def _clear_test_listener_plumbing(s) -> None:
    params = {"like": "evt:test_listener%"}
    await s.execute(text("DELETE FROM task_queue WHERE topic LIKE :like"), params)
    await s.execute(text("DELETE FROM consumed_events WHERE consumer LIKE :like"), params)
    await s.execute(text("DELETE FROM dispatched_consumers WHERE topic LIKE :like"), params)
    await s.execute(text("DELETE FROM event_dispatch_cursors WHERE topic LIKE :like"), params)


@pytest_asyncio.fixture
async def iso():
    # Mark existing facts checked, so tick() sees only this test's; restore wiring and handlers.
    _clear_engine_caches()
    saved_wiring = wiring.snapshot()
    saved_handlers = dict(_handlers)
    async with db.admin_session_factory()() as s:
        await s.execute(
            text("UPDATE business_events SET checked_at = now() WHERE checked_at IS NULL")
        )
        await _clear_test_listener_plumbing(s)
        await s.commit()
    yield
    async with db.admin_session_factory()() as s:
        await s.execute(text("DELETE FROM business_events WHERE kind LIKE 'test_listener.%'"))
        await _clear_test_listener_plumbing(s)
        await s.commit()
    _handlers.clear()
    _handlers.update(saved_handlers)
    wiring.restore(saved_wiring)
    await db._admin_engine().dispose()
    _clear_engine_caches()


async def _noop(session, event) -> None:
    return None


async def _seed(actor: uuid.UUID, *, label: str = "Hi", entity_id: uuid.UUID | None = None) -> None:
    await seed_fact(
        BusinessEventRecord(
            app_name="test_listener",
            verb="happened",
            user_id=actor,
            entity_id=entity_id,
            payload={"label": label},
        )
    )


async def _topics() -> list[str]:
    async with db.admin_session_factory()() as s:
        queued = await s.execute(
            text(
                "SELECT topic FROM task_queue WHERE topic LIKE 'evt:test_listener%' ORDER BY topic"
            )
        )
        return [r[0] for r in queued]


async def _unchecked(kind: str) -> int:
    async with db.admin_session_factory()() as s:
        return await s.scalar(
            text("SELECT count(*) FROM business_events WHERE kind = :k AND checked_at IS NULL"),
            {"k": kind},
        )


@pytest.mark.asyncio
async def test_tick_enqueues_one_task_per_subscriber_and_marks_the_fact_dispatched(iso):
    events.on(_TailEvent, _noop, name="counter", app="test_listener", as_actor=False)
    events.on(_TailEvent, _noop, name="search", app="test_listener", as_actor=False)
    await _seed(uuid.uuid7())

    dispatched = await EventListener(0).tick()

    assert dispatched == 1
    assert await _topics() == [
        "evt:test_listener.happened:counter",
        "evt:test_listener.happened:search",
    ]
    assert await _unchecked("test_listener.happened") == 0


@pytest.mark.asyncio
async def test_worker_runs_the_consumer_with_the_reconstructed_typed_event(iso):
    seen: list[object] = []

    async def handler(session, event) -> None:
        seen.append(event)

    events.on(_TailEvent, handler, name="counter", app="test_listener", as_actor=False)
    actor, eid = uuid.uuid7(), uuid.uuid7()
    await _seed(actor, label="Ship it", entity_id=eid)

    factory = db.admin_session_factory()
    await EventListener(0, session_factory=factory).tick()
    worker = TaskWorker(0, session_factory=factory)
    while await worker.tick():
        pass

    assert len(seen) == 1
    event = seen[0]
    assert isinstance(event, _TailEvent)
    assert event.user_id == actor
    assert event.entity_id == eid
    assert event.label == "Ship it"


@pytest.mark.asyncio
async def test_the_consumer_receives_the_event_stamped_with_the_facts_instant(iso):
    """Not when a retry finally delivered it."""
    seen: list[BusinessEvent] = []

    async def handler(session, event) -> None:
        seen.append(event)

    events.on(_TailEvent, handler, name="counter", app="test_listener", as_actor=False)
    await _seed(uuid.uuid7())
    async with db.admin_session_factory()() as s:
        stored = await s.scalar(
            text(
                "SELECT created_at FROM business_events "
                "WHERE kind = 'test_listener.happened' ORDER BY id DESC LIMIT 1"
            )
        )

    factory = db.admin_session_factory()
    await EventListener(0, session_factory=factory).tick()
    worker = TaskWorker(0, session_factory=factory)
    while await worker.tick():
        pass

    assert len(seen) == 1
    assert seen[0].created_at == stored


@pytest.mark.asyncio
async def test_a_reaction_runs_under_the_originating_requests_correlation(iso):
    """The fact's request_id is bound while the handler runs, so its logs join that request."""
    seen: dict[str, object] = {}

    async def handler(session, event) -> None:
        seen.update(structlog.contextvars.get_contextvars())

    events.on(_TailEvent, handler, name="counter", app="test_listener", as_actor=False)
    request_id = uuid.uuid7()
    await seed_fact(
        BusinessEventRecord(
            app_name="test_listener",
            verb="happened",
            user_id=uuid.uuid7(),
            request_id=request_id,
            payload={"label": "x"},
        )
    )

    factory = db.admin_session_factory()
    await EventListener(0, session_factory=factory).tick()
    worker = TaskWorker(0, session_factory=factory)
    while await worker.tick():
        pass

    assert seen.get("request_id") == str(request_id)


@pytest.mark.asyncio
async def test_a_reaction_parked_for_good_logs_its_failure_under_the_facts_delivery_context(iso):
    """``queue.task_failed`` is logged outside the handler's binding, and still carries the fact's
    request_id, user_id and org_id."""

    async def handler(session, event) -> None:
        raise RuntimeError("boom")

    events.on(_TailEvent, handler, name="always_fails", app="test_listener", as_actor=False)
    request_id, org_id, actor = uuid.uuid7(), uuid.uuid7(), uuid.uuid7()
    await seed_fact(
        BusinessEventRecord(
            app_name="test_listener",
            verb="happened",
            user_id=actor,
            org_id=org_id,
            request_id=request_id,
            payload={"label": "x"},
        )
    )

    factory = db.admin_session_factory()
    await EventListener(0, session_factory=factory).tick()
    async with db.admin_session_factory()() as s:
        await s.execute(
            text(
                "UPDATE task_queue SET max_attempts = 1 "
                "WHERE topic = 'evt:test_listener.happened:always_fails'"
            )
        )
        await s.commit()

    # `capture_logs()` drops the configured processors, `merge_contextvars` included.
    with capture_logs(processors=(structlog.contextvars.merge_contextvars,)) as logs:
        worker = TaskWorker(0, session_factory=factory)
        while await worker.tick():
            pass

    failed = [entry for entry in logs if entry["event"] == "queue.task_failed"]
    assert len(failed) == 1
    assert (failed[0]["request_id"], failed[0]["user_id"], failed[0]["org_id"]) == (
        str(request_id),
        str(actor),
        str(org_id),
    )


@pytest.mark.asyncio
async def test_an_unroutable_kind_is_surfaced_as_an_issue_but_still_marked_checked(iso):
    """Unlike a kind nobody listens to, an unknown kind is a bug. Nothing is enqueued."""
    async with db.admin_session_factory()() as s:
        await s.execute(
            text(
                "INSERT INTO business_events (app_name, verb, user_id) "
                "VALUES ('test_listener', 'legacy', NULL)"
            )
        )
        await s.commit()

    with capture_logs() as logs:
        assert await EventListener(0).tick() == 1
    surfaced = [entry for entry in logs if entry["event"] == "listener.unroutable_fact"]
    assert len(surfaced) == 1
    assert surfaced[0]["log_level"] == "error"
    assert surfaced[0]["kind"] == "test_listener.legacy"
    assert await _topics() == []
    assert await _unchecked("test_listener.legacy") == 0


def test_forget_apps_register_durable_consumers_of_user_deleted():
    """Checked by topic: shared may not import the contexts."""
    import apps.main  # noqa: F401

    topics = set(_handlers)
    assert "evt:auth.user_deleted:organizations_forget" in topics
    assert "evt:auth.user_deleted:profile_forget" in topics


def test_org_seed_apps_register_durable_consumers_of_organization_created():
    """Checked by topic: shared may not import the contexts."""
    import apps.main  # noqa: F401

    topics = set(_handlers)
    for app in ("todo", "files", "calendar", "learning", "pages"):
        assert f"evt:organizations.created:{app}_welcome" in topics


@pytest.mark.asyncio
async def test_tick_runs_spread_handlers_per_instance_off_the_trail(iso):
    """Replayed as its typed event, without being claimed or marked dispatched."""
    own = EventWiring()
    seen: list[object] = []

    async def apply(event: _SpreadEvent) -> None:
        seen.append(event)

    EventBus(own).spread(_SpreadEvent, apply)
    await seed_fact(
        BusinessEventRecord(app_name="test_listener", verb="spread", payload={"value": "on"})
    )

    await EventListener(0, wiring=own).tick()

    assert len(seen) == 1
    assert isinstance(seen[0], _SpreadEvent)
    assert seen[0].value == "on"


def _spread_record(value: str) -> BusinessEventRecord:
    return BusinessEventRecord(app_name="test_listener", verb="spread", payload={"value": value})


@pytest.mark.asyncio
async def test_spread_reaches_a_fact_that_commits_after_a_later_one(iso):
    """``early`` holds the lower key but commits after a tick has seen ``late``: it surfaces
    below the cursor, and must still be applied."""
    own = EventWiring()
    seen: list[str | None] = []

    async def apply(event: _SpreadEvent) -> None:
        seen.append(event.value)

    EventBus(own).spread(_SpreadEvent, apply)
    listener = EventListener(0, wiring=own)
    async with db.admin_session_factory()() as in_flight:
        await seed_fact_on(in_flight, _spread_record("early"))
        await seed_fact(_spread_record("late"))
        await listener.tick()
        await in_flight.commit()

    await listener.tick()

    assert seen == ["late", "early"]


@pytest.mark.asyncio
async def test_a_fact_that_cannot_be_rebuilt_is_skipped_and_the_spread_cursor_advances(iso):
    """Else every later tick replays the poison fact; the healthy one behind it still runs."""
    own = EventWiring()
    seen: list[_StrictSpreadEvent] = []

    async def apply(event: _StrictSpreadEvent) -> None:
        seen.append(event)

    EventBus(own).spread(_StrictSpreadEvent, apply)
    for payload in ({}, {"value": "on"}):
        await seed_fact(
            BusinessEventRecord(app_name="test_listener", verb="strict_spread", payload=payload)
        )

    listener = EventListener(0, wiring=own)
    with capture_logs() as logs:
        await listener.tick()

    assert [e.value for e in seen] == ["on"]
    failed = [entry for entry in logs if entry["event"] == "listener.reconstruct_failed"]
    assert len(failed) == 1
    assert failed[0]["log_level"] == "error"
    await listener.tick()
    assert [e.value for e in seen] == ["on"]


@pytest.mark.asyncio
async def test_a_spread_handler_that_refuses_is_surfaced_as_an_issue(iso):
    """The instance is left on stale settings and nothing retries: a bug. The cursor still
    advances, or propagation would freeze."""
    own = EventWiring()

    async def refuse(_event: _SpreadEvent) -> None:
        raise RuntimeError("the reload found no such setting")

    EventBus(own).spread(_SpreadEvent, refuse)
    await seed_fact(
        BusinessEventRecord(app_name="test_listener", verb="spread", payload={"value": "on"})
    )

    with capture_logs() as logs:
        await EventListener(0, wiring=own).tick()

    surfaced = [e for e in logs if e["event"] == "listener.spread_handler_failed"]
    assert [(e["kind"], e["log_level"]) for e in surfaced] == [("test_listener.spread", "error")]


@pytest.mark.asyncio
async def test_a_second_tick_does_not_refan_a_dispatched_fact(iso):
    events.on(_TailEvent, _noop, name="counter", app="test_listener", as_actor=False)
    await _seed(uuid.uuid7())

    assert await EventListener(0).tick() == 1
    assert await EventListener(0).tick() == 0
    assert await _topics() == ["evt:test_listener.happened:counter"]


@pytest.mark.asyncio
async def test_a_wiring_without_the_consumer_does_not_foreclose_it_for_one_that_has_it(iso):
    """The issue's own reproduction: two listeners on two wirings, only one of which registers
    the consumer. The one without it must not mark the fact fully delivered — the listener
    whose wiring does carry the consumer still owes it the task."""
    without_consumer = EventWiring()
    with_consumer = EventWiring()
    EventBus(with_consumer).on(
        _TailEvent, _noop, name="counter", app="test_listener", as_actor=False
    )
    await _seed(uuid.uuid7())

    await EventListener(0, wiring=without_consumer).tick()
    await EventListener(0, wiring=with_consumer).tick()

    assert await _topics() == ["evt:test_listener.happened:counter"]


@pytest.mark.asyncio
async def test_a_burst_larger_than_the_batch_size_is_dispatched_in_one_tick(iso):
    """The backlog scan is unbounded, the same shape as its spread sibling — a small batch only
    bounds the routability claim, never how much of a consumer's backlog one tick clears. A read
    anchored at the cursor and capped at ``batch`` would otherwise starve anything past the first
    batch until the whole window settles, however many ticks passed."""
    events.on(_TailEvent, _noop, name="counter", app="test_listener", as_actor=False)
    for _ in range(5):
        await _seed(uuid.uuid7())

    await EventListener(0, batch_size=2).tick()

    assert await _topics() == ["evt:test_listener.happened:counter"] * 5


@pytest.mark.asyncio
async def test_a_consumer_registered_on_a_base_type_still_receives_a_subclass_fact(iso):
    """Mirrors ``consumers_of``'s own MRO walk (see ``test_bus.py``): a subscriber on a concrete
    base must still be reached by a concrete subclass's own, distinct kind."""
    events.on(_TailEvent, _noop, name="counter", app="test_listener", as_actor=False)
    await seed_fact(
        BusinessEventRecord(app_name="test_listener", verb="happened_sub", user_id=uuid.uuid7())
    )

    await EventListener(0).tick()

    assert await _topics() == ["evt:test_listener.happened:counter"]
