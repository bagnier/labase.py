"""Durable async-consumer registry — subscriber registration, MRO fan-out set, idempotency ledger.

Delivery itself (log → task_queue) is the tailer's job; see test_tailer.py.
"""

import uuid
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import text

from apps.shared import outbox
from apps.shared.events import BusinessEvent
from apps.shared.persistence import database as db
from apps.shared.queue import _handlers


@dataclass(frozen=True, kw_only=True)
class _Ticked(BusinessEvent):
    kind = "test_outbox.ticked"
    label: str | None = None


class _TickedSub(_Ticked):
    kind = "test_outbox.ticked_sub"


def _clear_engine_caches() -> None:
    db._user_engine.cache_clear()
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


@pytest_asyncio.fixture(autouse=True)
async def outbox_isolation():
    # Snapshot the process-wide registries: apps.main (imported by the e2e drivers) registered
    # real task handlers / async subs at mount, so we restore rather than clear — a global reset
    # would silently unregister the app's own consumers for every later test.
    _clear_engine_caches()
    saved_handlers = dict(_handlers)
    saved_subs = {k: list(v) for k, v in outbox._async_subs.items()}
    async with db.admin_session_factory()() as session:
        await session.execute(text("DELETE FROM consumed WHERE topic LIKE 'evt:test_outbox%'"))
        await session.commit()
    yield
    async with db.admin_session_factory()() as session:
        await session.execute(text("DELETE FROM consumed WHERE topic LIKE 'evt:test_outbox%'"))
        await session.commit()
    _handlers.clear()
    _handlers.update(saved_handlers)
    outbox._async_subs.clear()
    outbox._async_subs.update(saved_subs)
    await db._user_engine().dispose()
    await db._admin_engine().dispose()
    _clear_engine_caches()


async def _noop(session, event) -> None:
    return None


# ── on_async registration ─────────────────────────────────────────────────────────────────


def test_on_async_rejects_a_duplicate_subscriber_name_for_the_same_event():
    outbox.on_async(_Ticked, "counter", _noop)
    with pytest.raises(ValueError):
        outbox.on_async(_Ticked, "counter", _noop)


def test_subscribers_for_walks_the_mro_so_a_base_subscription_catches_subclasses():
    outbox.on_async(_Ticked, "counter", _noop)
    # A subscriber on the base type is delivered for a subclass event too.
    topics = [s.topic for s in outbox.subscribers_for(_TickedSub)]
    assert topics == ["evt:test_outbox.ticked:counter"]
    # And an exact-type event sees its own subscriber.
    assert [s.topic for s in outbox.subscribers_for(_Ticked)] == ["evt:test_outbox.ticked:counter"]


# ── already_consumed (idempotency substrate, keyed on the business_events row id) ────────────


@pytest.mark.asyncio
async def test_already_consumed_is_false_first_then_true():
    topic, event_id = "evt:test_outbox.ticked:counter", 424242
    async with db.admin_session_factory()() as session:
        assert await outbox.already_consumed(session, topic, event_id) is False
        assert await outbox.already_consumed(session, topic, event_id) is True
        await session.commit()


@pytest.mark.asyncio
async def test_idempotent_consumer_runs_once_across_a_redelivery():
    calls: list[object] = []

    async def handler(session, event) -> None:
        calls.append(event)

    outbox.on_async(_Ticked, "counter", handler, idempotent=True)
    wrapper = _handlers["evt:test_outbox.ticked:counter"]
    payload = {"actor_id": str(uuid.uuid4()), "org_id": "o", "label": "Buy milk", "event_id": 99}
    async with db.admin_session_factory()() as session:
        await wrapper(session, payload)  # first delivery
        await wrapper(session, payload)  # at-least-once re-delivery, same event_id
        await session.commit()
    assert len(calls) == 1
    assert isinstance(calls[0], _Ticked)  # reconstructed as the typed event, not a dict
