"""The event bus's durable-consumer surface — ``on`` registration, the MRO fan-out set, and the
idempotency guard the reconstructed-typed-event wrapper folds in.

Delivery itself (log → task_queue) is the listener's job; see test_listener.py.
"""

import uuid
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import text

from apps.shared.events import BusinessEvent
from apps.shared.events.bus import events
from apps.shared.events.registry import registry
from apps.shared.events.repository import EventRepository
from apps.shared.persistence import database as db
from apps.shared.queue import _handlers


@dataclass(frozen=True, kw_only=True)
class _Ticked(BusinessEvent):
    kind = "test_bus.ticked"
    label: str | None = None


class _TickedSub(_Ticked):
    kind = "test_bus.ticked_sub"


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


# ── on() registration ────────────────────────────────────────────────────────────────────────


def test_on_rejects_a_duplicate_consumer_name_for_the_same_event():
    events.on(_Ticked, _noop, name="counter")
    with pytest.raises(ValueError):
        events.on(_Ticked, _noop, name="counter")


def test_subscribers_for_walks_the_mro_so_a_base_subscription_catches_subclasses():
    events.on(_Ticked, _noop, name="counter")
    expected = ["evt:test_bus.ticked:counter"]
    # A subscriber on the base type is delivered for a subclass event too.
    assert [s.topic for s in registry.subscribers_for(_TickedSub)] == expected
    # And an exact-type event sees its own subscriber.
    assert [s.topic for s in registry.subscribers_for(_Ticked)] == expected


# ── already_consumed (idempotency substrate, keyed on the business_events row id) ─────────────


@pytest.mark.asyncio
async def test_already_consumed_is_false_first_then_true():
    topic, event_id = "evt:test_bus.ticked:counter", 424242
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

    events.on(_Ticked, handler, name="counter", idempotent=True)
    wrapper = _handlers["evt:test_bus.ticked:counter"]
    payload = {"actor_id": str(uuid.uuid4()), "org_id": "o", "label": "Buy milk", "event_id": 99}
    async with db.admin_session_factory()() as session:
        await wrapper(session, payload)  # first delivery
        await wrapper(session, payload)  # at-least-once re-delivery, same event_id
        await session.commit()
    assert len(calls) == 1
    assert isinstance(calls[0], _Ticked)  # reconstructed as the typed event, not a dict
