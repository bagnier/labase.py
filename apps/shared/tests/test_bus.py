"""The event bus's registration surface and the wiring it writes — ``declare`` ownership and the
emit gate, ``on`` registration with the MRO fan-out set, the idempotency guard the
reconstructed-typed-event wrapper folds in, and how a test isolates or restores the wiring.

Delivery itself (journal → task_queue) is the listener's job; see test_listener.py.
"""

import uuid
from dataclasses import dataclass
from typing import cast

import pytest
import pytest_asyncio
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events import BusinessEvent
from apps.shared.events.bus import EventBus, events
from apps.shared.events.repository import EventRepository
from apps.shared.events.wiring import EventWiring, wiring
from apps.shared.persistence import database as db
from apps.shared.queue import _handlers


@dataclass(frozen=True, kw_only=True)
class _Ticked(BusinessEvent):
    app_name = "test_bus"
    verb = "ticked"
    label: str | None = None


class _TickedSub(_Ticked):
    verb = "ticked_sub"


def _clear_engine_caches() -> None:
    db._user_engine.cache_clear()
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


@pytest_asyncio.fixture(autouse=True)
async def bus_isolation():
    # Snapshot what the process already wired: apps.main (imported by the e2e drivers) registered
    # real task handlers / durable consumers at mount, so we restore rather than clear — a global
    # reset would silently unregister the app's own consumers for every later test.
    _clear_engine_caches()
    saved_handlers = dict(_handlers)
    saved_wiring = wiring.snapshot()
    async with db.admin_session_factory()() as session:
        await session.execute(text("DELETE FROM consumed WHERE topic LIKE 'evt:test_bus%'"))
        await session.commit()
    yield
    async with db.admin_session_factory()() as session:
        await session.execute(text("DELETE FROM consumed WHERE topic LIKE 'evt:test_bus%'"))
        await session.commit()
    _handlers.clear()
    _handlers.update(saved_handlers)
    wiring.restore(saved_wiring)
    await db._user_engine().dispose()
    await db._admin_engine().dispose()
    _clear_engine_caches()


async def _noop(session, event) -> None:
    return None


# ── declare() ownership + emit gate ──────────────────────────────────────────────────────────


def test_declare_records_the_owner_app_and_gates_emit():
    # Declaring activates a fact; it never attributes one. The owner is the app the event itself
    # names, so a mount cannot spell it differently from the class.
    own = EventWiring()
    assert own.is_declared(_Ticked) is False
    own.declare(_Ticked)
    assert own.is_declared(_Ticked) is True
    assert own.owner_of(_Ticked) == "test_bus"
    assert own.by_app() == {"test_bus": [_Ticked]}


def test_declare_rejects_an_event_that_names_no_app_and_verb():
    # Without both halves an event has no kind: it never entered the catalog, so a persisted fact
    # could not be rebuilt from it. Usually an abstract base handed over instead of its subclasses.
    class _Abstract(BusinessEvent):
        pass

    own = EventWiring()
    with pytest.raises(ValueError, match="_Abstract"):
        own.declare(_Abstract)


@pytest.mark.asyncio
async def test_emit_refuses_an_undeclared_event():
    bus = EventBus()
    with pytest.raises(ValueError, match="declared by no app"):
        # The gate runs before the session is ever touched, so a stand-in is enough here.
        await bus.emit(_Ticked(), cast(AsyncSession, None))  # no app declared it


# ── on() registration ────────────────────────────────────────────────────────────────────────


def test_on_rejects_a_duplicate_consumer_name_for_the_same_event():
    events.on(_Ticked, _noop, name="counter", app="test_bus")
    with pytest.raises(ValueError, match="counter"):
        events.on(_Ticked, _noop, name="counter", app="test_bus")


def test_consumers_of_walks_the_mro_so_a_base_subscription_catches_subclasses():
    events.on(_Ticked, _noop, name="counter", app="test_bus")
    expected = ["evt:test_bus.ticked:counter"]
    # A subscriber on the base type is delivered for a subclass event too.
    assert [s.topic for s in wiring.consumers_of(_TickedSub)] == expected
    # And an exact-type event sees its own subscriber.
    assert [s.topic for s in wiring.consumers_of(_Ticked)] == expected


# ── snapshot/restore: what a test registers on the live bus, put back ─────────────────────────


def test_restoring_a_snapshot_drops_what_was_registered_after_it():
    # A test that exercises the *real* fan-out has to register on the process-wide bus, then put
    # back what it found — otherwise its consumer keeps firing for every later test in the run.
    own = EventWiring()
    own.declare(_Ticked)
    own.add_consumer(_Ticked, "before", as_actor=False, app="test_bus")
    saved = own.snapshot()

    own.declare(_TickedSub)
    own.add_consumer(_Ticked, "after", as_actor=False, app="test_bus")
    own.restore(saved)

    assert [r.name for r in own.consumers_of(_Ticked)] == ["before"]
    assert own.is_declared(_TickedSub) is False
    # And the snapshot is a copy, not a view: mutating after taking it left it untouched, so the
    # same snapshot restores the same state twice (a fixture reused across tests in one module).
    own.add_consumer(_Ticked, "after", as_actor=False, app="test_bus")
    own.restore(saved)
    assert [r.name for r in own.consumers_of(_Ticked)] == ["before"]


def test_a_bus_given_its_own_wiring_stays_out_of_the_process_one():
    # Handing a bus a fresh wiring is how a test keeps its registrations to itself — the default
    # is the process's, which the live `events` writes. What events *exist* is shared either way:
    # that is the catalog, filled at import, and there is nothing to isolate about it.
    own = EventWiring()
    EventBus(own).on(_Ticked, _noop, name="isolated", app="test_bus")

    events.on(_Ticked, _noop, name="counter", app="test_bus")

    assert [r.name for r in own.consumers_of(_Ticked)] == ["isolated"]
    assert [r.name for r in wiring.consumers_of(_Ticked)] == ["counter"]


# ── already_consumed (idempotency substrate, keyed on the business_events record id) ──────────


@pytest.mark.asyncio
async def test_already_consumed_is_false_first_then_true():
    topic, event_id = "evt:test_bus.ticked:counter", uuid.uuid7()
    async with db.admin_session_factory()() as session:
        repo = EventRepository(session)
        assert await repo.already_consumed(topic, event_id) is False
        assert await repo.already_consumed(topic, event_id) is True
        await session.commit()


@pytest.mark.asyncio
async def test_idempotent_consumer_runs_once_across_a_redelivery():
    calls: list[object] = []

    async def handler(session, event) -> None:
        calls.append(event)

    events.on(_Ticked, handler, name="counter", app="test_bus", idempotent=True)
    wrapper = _handlers["evt:test_bus.ticked:counter"]
    payload = {
        "user_id": str(uuid.uuid7()),
        "org_id": str(uuid.uuid7()),
        "label": "Buy milk",
        "event_id": str(uuid.uuid7()),
    }
    async with db.admin_session_factory()() as session:
        await wrapper(session, payload)  # first delivery
        await wrapper(session, payload)  # at-least-once re-delivery, same event_id
        await session.commit()
    assert len(calls) == 1
    assert isinstance(calls[0], _Ticked)  # reconstructed as the typed event, not a dict


@pytest.mark.asyncio
async def test_a_reaction_runs_with_the_request_and_fact_bound_to_its_log_context():
    # A reaction runs off the journal on a background task with no request context of its own. The
    # wrapper binds the originating request_id (correlation) and the fact's event_id (causation)
    # onto structlog, so the reaction's log lines join the emitting request's timeline — then
    # restores the context, so nothing leaks into the next task the worker runs.
    seen: dict[str, object] = {}

    async def handler(session, event) -> None:
        seen.update(structlog.contextvars.get_contextvars())

    events.on(_Ticked, handler, name="corr", app="test_bus", idempotent=False)
    wrapper = _handlers["evt:test_bus.ticked:corr"]
    request_id, event_id = uuid.uuid7(), uuid.uuid7()
    payload = {"label": "x", "request_id": str(request_id), "event_id": str(event_id)}

    # idempotent=False → the ledger check is skipped, so no DB session is touched by the wrapper.
    await wrapper(cast(AsyncSession, None), payload)

    assert seen["request_id"] == str(request_id)
    assert seen["event_id"] == str(event_id)
    assert "request_id" not in structlog.contextvars.get_contextvars()  # restored after the handler
