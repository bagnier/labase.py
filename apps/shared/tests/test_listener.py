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
from apps.shared.tests.journal_seed import seed_fact


@dataclass(frozen=True, kw_only=True)
class _TailEvent(BusinessEvent):
    app_name = "test_listener"
    verb = "happened"
    label: str | None = None


@dataclass(frozen=True, kw_only=True)
class _SpreadEvent(BusinessEvent):
    app_name = "test_listener"
    verb = "spread"
    value: str | None = None


@dataclass(frozen=True, kw_only=True)
class _StrictSpreadEvent(BusinessEvent):
    """A spread event with a *required* payload field: a stored fact missing it cannot rebuild."""

    app_name = "test_listener"
    verb = "strict_spread"
    value: str


def _clear_engine_caches() -> None:
    db._user_engine.cache_clear()
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


@pytest_asyncio.fixture
async def iso():
    # Isolate the listener's global view: mark every pre-existing fact dispatched so tick() sees
    # only what this test inserts. Restore the process-wide wiring and task handlers afterwards.
    _clear_engine_caches()
    saved_wiring = wiring.snapshot()
    saved_handlers = dict(_handlers)
    async with db.admin_session_factory()() as s:
        await s.execute(
            text("UPDATE business_events SET dispatched_at = now() WHERE dispatched_at IS NULL")
        )
        await s.execute(text("DELETE FROM task_queue WHERE topic LIKE 'evt:test_listener%'"))
        await s.execute(
            text("DELETE FROM consumed_events WHERE consumer LIKE 'evt:test_listener%'")
        )
        await s.commit()
    yield
    async with db.admin_session_factory()() as s:
        await s.execute(text("DELETE FROM business_events WHERE kind LIKE 'test_listener.%'"))
        await s.execute(text("DELETE FROM task_queue WHERE topic LIKE 'evt:test_listener%'"))
        await s.execute(
            text("DELETE FROM consumed_events WHERE consumer LIKE 'evt:test_listener%'")
        )
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


async def _undispatched(kind: str) -> int:
    async with db.admin_session_factory()() as s:
        return await s.scalar(
            text("SELECT count(*) FROM business_events WHERE kind = :k AND dispatched_at IS NULL"),
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
    assert await _undispatched("test_listener.happened") == 0


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
    """A durable consumer must reason about *when the fact happened* — the journal's created_at —
    not when a retry/park finally delivered it. The delivered event carries the record's instant."""
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
    assert seen[0].created_at == stored  # the fact's instant, rebuilt from the record


@pytest.mark.asyncio
async def test_a_reaction_runs_under_the_originating_requests_correlation(iso):
    """The reaction runs off the journal on a background task with no request of its own; delivery
    wrapper binds the fact's originating request_id onto structlog, so the reaction's log lines join
    the emitting request's timeline. Assert it is bound while the handler runs."""
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
async def test_an_unroutable_kind_is_surfaced_as_an_issue_but_still_marked_dispatched(iso):
    """A kind with no registered class can be routed to no one — a fact we cannot even name. That is
    not the benign "nobody listens" no-op: it is logged at exception level (the capture seam folds
    it into a console Issue), so it stops being lost in silence. The cursor still advances: the
    record is marked dispatched and nothing is enqueued."""
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
    assert surfaced[0]["log_level"] == "error"  # exception level → captured as an Issue
    assert surfaced[0]["kind"] == "test_listener.legacy"
    assert await _topics() == []
    assert await _undispatched("test_listener.legacy") == 0


def test_forget_apps_register_durable_consumers_of_user_deleted():
    """Account deletion cleanup runs off the listener: organizations and profile each declare one
    async consumer of UserDeleted (auth.user_deleted), keyed by topic (shared may not import the
    bounded contexts to name the handlers)."""
    import apps.main  # noqa: F401

    topics = set(_handlers)
    assert "evt:auth.user_deleted:organizations_forget" in topics
    assert "evt:auth.user_deleted:profile_forget" in topics


def test_org_seed_apps_register_durable_consumers_of_organization_created():
    """Importing the composition root mounts every app; each welcome-seed app declares a durable
    async consumer of OrganizationCreated via the manifest's consumes_when_enabled. Checked by
    topic string (shared may not import a bounded context to name the event type)."""
    import apps.main  # noqa: F401

    topics = set(_handlers)
    for app in ("todo", "files", "calendar", "learning", "pages"):
        assert f"evt:organizations.created:{app}_welcome" in topics


@pytest.mark.asyncio
async def test_tick_runs_spread_handlers_per_instance_off_the_trail(iso):
    """A spread fact is replayed to this process's spread handler off the journal — no claim, no
    dispatch mark (every instance applies it). Reconstructed as its typed event. Its own wiring
    isolates the spread handler; the catalog is process-wide, so class_for resolves the kind."""
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


@pytest.mark.asyncio
async def test_a_fact_that_cannot_be_rebuilt_is_skipped_and_the_spread_cursor_advances(iso):
    """A fact whose payload can't rebuild its typed event (a field added to the class after it was
    written, a hand-inserted one) must not wedge the spread path: without advancing the cursor,
    every later tick would replay the same poison fact and none would ever propagate again. It is
    logged, skipped, and the healthy fact behind it still runs."""
    own = EventWiring()
    seen: list[_StrictSpreadEvent] = []

    async def apply(event: _StrictSpreadEvent) -> None:
        seen.append(event)

    EventBus(own).spread(_StrictSpreadEvent, apply)
    for payload in ({}, {"value": "on"}):  # poison first — uuid7 keeps the healthy one behind
        await seed_fact(
            BusinessEventRecord(app_name="test_listener", verb="strict_spread", payload=payload)
        )

    listener = EventListener(0, wiring=own)
    with capture_logs() as logs:
        await listener.tick()

    assert [e.value for e in seen] == ["on"]
    # The poison fact is not swallowed as a warning: it is logged at exception level, so capture
    # seam records a console Issue for a fact that can no longer be rebuilt.
    failed = [entry for entry in logs if entry["event"] == "listener.reconstruct_failed"]
    assert len(failed) == 1
    assert failed[0]["log_level"] == "error"
    await listener.tick()  # cursor moved past both facts: nothing replays
    assert [e.value for e in seen] == ["on"]


@pytest.mark.asyncio
async def test_a_spread_handler_that_refuses_is_surfaced_as_an_issue(iso):
    """A ``spread`` handler is a config reload — the settings the console just changed reaching
    this instance. One that raises means this process is now running on stale values while every
    other one moved, and nothing retries it (spread has no claim and no queue). That is a defect,
    not a degradation, and used to be a ``warning`` inside a two-day window.

    The cursor still advances, like a fact that cannot be rebuilt: replaying a handler that
    refuses would freeze propagation for good."""
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
    assert await EventListener(0).tick() == 0  # nothing left undispatched
    assert await _topics() == ["evt:test_listener.happened:counter"]  # not duplicated
