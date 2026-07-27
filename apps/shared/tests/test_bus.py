"""The event bus's durable-consumer surface — ``on`` registration, the MRO fan-out set, and the
idempotency guard the reconstructed-typed-event wrapper folds in.

Delivery itself (log → task_queue) is the listener's job; see test_listener.py.
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
from apps.shared.events.registry import EventRegistry, registry
from apps.shared.events.repository import EventRepository
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
    # Snapshot the process-wide registries: apps.main (imported by the e2e drivers) registered
    # real task handlers / durable subs at mount, so we restore rather than clear — a global reset
    # would silently unregister the app's own consumers for every later test.
    _clear_engine_caches()
    saved_handlers = dict(_handlers)
    saved_subs = {k: list(v) for k, v in registry._async_subs.items()}
    async with db.admin_session_factory()() as session:
        await session.execute(text("DELETE FROM consumed WHERE topic LIKE 'evt:test_bus%'"))
        await session.commit()
    yield
    async with db.admin_session_factory()() as session:
        await session.execute(text("DELETE FROM consumed WHERE topic LIKE 'evt:test_bus%'"))
        await session.commit()
    _handlers.clear()
    _handlers.update(saved_handlers)
    registry._async_subs.clear()
    registry._async_subs.update(saved_subs)
    await db._user_engine().dispose()
    await db._admin_engine().dispose()
    _clear_engine_caches()


async def _noop(session, event) -> None:
    return None


# ── declare() ownership + emit gate ──────────────────────────────────────────────────────────


def test_declare_records_the_owner_app_and_gates_emit():
    # Declaring activates a fact; it never attributes one. The owner is the app the event itself
    # names, so a mount cannot spell it differently from the class.
    reg = EventRegistry()
    assert reg.is_declared(_Ticked) is False
    reg.declare_events(_Ticked)
    assert reg.is_declared(_Ticked) is True
    assert reg.owner_of(_Ticked) == "test_bus"
    assert reg.events_by_app() == {"test_bus": [_Ticked]}


def test_declare_rejects_an_event_that_names_no_app_and_verb():
    # Without both halves an event has no kind: it never entered the catalog, so a persisted row
    # could not be rebuilt from it. Usually an abstract base handed over instead of its subclasses.
    class _Abstract(BusinessEvent):
        pass

    reg = EventRegistry()
    with pytest.raises(ValueError, match="_Abstract"):
        reg.declare_events(_Abstract)


@pytest.mark.asyncio
async def test_emit_refuses_an_undeclared_event():
    bus = EventBus(EventRegistry())
    with pytest.raises(ValueError):
        await bus.emit(_Ticked())  # no app declared it


# ── on() registration ────────────────────────────────────────────────────────────────────────


def test_on_rejects_a_duplicate_consumer_name_for_the_same_event():
    events.on(_Ticked, _noop, name="counter", app="test_bus")
    with pytest.raises(ValueError):
        events.on(_Ticked, _noop, name="counter", app="test_bus")


def test_subscribers_for_walks_the_mro_so_a_base_subscription_catches_subclasses():
    events.on(_Ticked, _noop, name="counter", app="test_bus")
    expected = ["evt:test_bus.ticked:counter"]
    # A subscriber on the base type is delivered for a subclass event too.
    assert [s.topic for s in registry.subscribers_for(_TickedSub)] == expected
    # And an exact-type event sees its own subscriber.
    assert [s.topic for s in registry.subscribers_for(_Ticked)] == expected


# ── already_consumed (idempotency substrate, keyed on the business_events row id) ─────────────


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
    # A reaction runs off the trail on a background task with no request context of its own. The
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
