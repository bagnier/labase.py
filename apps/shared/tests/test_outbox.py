"""Outbox bridge — durable async fan-out of typed events over the task queue."""

import uuid
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import text

from apps.shared import outbox
from apps.shared.events import BusinessEvent
from apps.shared.persistence import database as db
from apps.shared.persistence.uow import bind_current_session, reset_current_session
from apps.shared.queue import _handlers


@dataclass(frozen=True, kw_only=True)
class _Ticked(BusinessEvent):
    kind = "test_outbox.ticked"
    label: str | None = None


@dataclass(frozen=True, kw_only=True)
class _WithSecret(BusinessEvent):
    kind = "test_outbox.secret"
    access_token: str | None = None


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
        await session.execute(text("DELETE FROM task_queue WHERE topic LIKE 'evt:test_outbox%'"))
        await session.execute(text("DELETE FROM consumed WHERE topic LIKE 'evt:test_outbox%'"))
        await session.commit()
    yield
    async with db.admin_session_factory()() as session:
        await session.execute(text("DELETE FROM task_queue WHERE topic LIKE 'evt:test_outbox%'"))
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


async def _topics_for(event_kind_prefix: str) -> list[str]:
    async with db.admin_session_factory()() as session:
        rows = await session.execute(
            text("SELECT topic FROM task_queue WHERE topic LIKE :p ORDER BY topic"),
            {"p": f"{event_kind_prefix}%"},
        )
        return [r[0] for r in rows]


# ── _event_payload ────────────────────────────────────────────────────────────────────────


def test_event_payload_round_trips_through_the_event_type():
    event = _Ticked(actor_id="a", org_id="o", entity_id="e", label="Buy milk")
    payload = outbox._event_payload(event)
    assert "event_id" in payload
    fields = {k: v for k, v in payload.items() if k != "event_id"}
    rebuilt = _Ticked(**fields)
    assert rebuilt == event


def test_event_payload_carries_a_fresh_event_id_each_call():
    event = _Ticked(actor_id="a")
    assert outbox._event_payload(event)["event_id"] != outbox._event_payload(event)["event_id"]


def test_event_payload_redacts_secret_fields():
    payload = outbox._event_payload(_WithSecret(actor_id="a", access_token="hunter2"))
    assert payload["access_token"] == "***"


# ── on_async registration ─────────────────────────────────────────────────────────────────


def test_on_async_rejects_a_duplicate_subscriber_name_for_the_same_event():
    outbox.on_async(_Ticked, "counter", _noop)
    with pytest.raises(ValueError):
        outbox.on_async(_Ticked, "counter", _noop)


# ── fan_out_durable ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_subscribers_is_a_zero_cost_no_op_without_a_session():
    # No async subs registered, no ambient session bound → must not raise and enqueue nothing.
    await outbox.fan_out_durable(_Ticked(actor_id="a"))
    assert await _topics_for("evt:test_outbox.ticked") == []


@pytest.mark.asyncio
async def test_subscribers_but_no_session_in_scope_raises():
    outbox.on_async(_Ticked, "counter", _noop)
    with pytest.raises(RuntimeError):
        await outbox.fan_out_durable(_Ticked(actor_id="a"))


@pytest.mark.asyncio
async def test_fan_out_enqueues_one_row_per_subscriber_on_the_given_session():
    outbox.on_async(_Ticked, "counter", _noop)
    outbox.on_async(_Ticked, "search", _noop)
    async with db.admin_session_factory()() as session:
        await outbox.fan_out_durable(_Ticked(actor_id=str(uuid.uuid4())), session=session)
        await session.commit()
    assert await _topics_for("evt:test_outbox.ticked") == [
        "evt:test_outbox.ticked:counter",
        "evt:test_outbox.ticked:search",
    ]


@pytest.mark.asyncio
async def test_fan_out_uses_the_ambient_session_when_none_passed():
    outbox.on_async(_Ticked, "counter", _noop)
    async with db.admin_session_factory()() as session:
        token = bind_current_session(session)
        try:
            await outbox.fan_out_durable(_Ticked(actor_id=str(uuid.uuid4())))
            await session.commit()
        finally:
            reset_current_session(token)
    assert await _topics_for("evt:test_outbox.ticked") == ["evt:test_outbox.ticked:counter"]


# ── EventBus.emit integration ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emit_fans_out_durably_on_the_passed_session():
    from apps.shared.bus import EventBus

    outbox.on_async(_Ticked, "counter", _noop)
    async with db.admin_session_factory()() as session:
        await EventBus().emit(_Ticked(actor_id=str(uuid.uuid4())), session=session)
        await session.commit()
    assert await _topics_for("evt:test_outbox.ticked") == ["evt:test_outbox.ticked:counter"]


@pytest.mark.asyncio
async def test_a_rolled_back_transaction_discards_the_enqueued_rows():
    # Atomic by construction: the durable delivery is written on the mutation's session, so if
    # that transaction rolls back (a later error in the request), the delivery never happened.
    from apps.shared.bus import EventBus

    outbox.on_async(_Ticked, "counter", _noop)
    async with db.admin_session_factory()() as session:
        await EventBus().emit(_Ticked(actor_id=str(uuid.uuid4())), session=session)
        await session.rollback()
    assert await _topics_for("evt:test_outbox.ticked") == []


# ── already_consumed (idempotency substrate) ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_already_consumed_is_false_first_then_true():
    topic, event_id = "evt:test_outbox.ticked:counter", str(uuid.uuid4())
    async with db.admin_session_factory()() as session:
        assert await outbox.already_consumed(session, topic, event_id) is False
        assert await outbox.already_consumed(session, topic, event_id) is True
        await session.commit()


@pytest.mark.asyncio
async def test_idempotent_consumer_runs_once_across_a_redelivery():
    from apps.shared.queue import _handlers

    calls: list[object] = []

    async def handler(session, event) -> None:
        calls.append(event)

    outbox.on_async(_Ticked, "counter", handler, idempotent=True)
    wrapper = _handlers["evt:test_outbox.ticked:counter"]
    payload = outbox._event_payload(_Ticked(actor_id=str(uuid.uuid4()), org_id="o"))
    async with db.admin_session_factory()() as session:
        await wrapper(session, payload)  # first delivery
        await wrapper(session, payload)  # at-least-once re-delivery, same event_id
        await session.commit()
    assert len(calls) == 1
