"""The event tailer — reads the business_events log and fans each fact to its async consumers."""

import uuid
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import text

from apps.shared import outbox
from apps.shared.events import BusinessEvent
from apps.shared.observability.business_events import insert_business_event
from apps.shared.persistence import database as db
from apps.shared.queue import TaskWorker, _handlers
from apps.shared.tailer import EventTailer


@dataclass(frozen=True, kw_only=True)
class _TailEvent(BusinessEvent):
    kind = "test_tailer.happened"
    label: str | None = None


def _clear_engine_caches() -> None:
    db._user_engine.cache_clear()
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


@pytest_asyncio.fixture
async def iso():
    # Isolate the tailer's global view: mark every pre-existing fact dispatched so tick() sees only
    # rows this test inserts. Restore the process-wide sub/handler registries afterwards.
    _clear_engine_caches()
    saved_subs = {k: list(v) for k, v in outbox._async_subs.items()}
    saved_handlers = dict(_handlers)
    async with db.admin_session_factory()() as s:
        await s.execute(
            text("UPDATE business_events SET dispatched_at = now() WHERE dispatched_at IS NULL")
        )
        await s.execute(text("DELETE FROM task_queue WHERE topic LIKE 'evt:test_tailer%'"))
        await s.execute(text("DELETE FROM consumed WHERE topic LIKE 'evt:test_tailer%'"))
        await s.commit()
    yield
    async with db.admin_session_factory()() as s:
        await s.execute(text("DELETE FROM business_events WHERE kind LIKE 'test_tailer.%'"))
        await s.execute(text("DELETE FROM task_queue WHERE topic LIKE 'evt:test_tailer%'"))
        await s.execute(text("DELETE FROM consumed WHERE topic LIKE 'evt:test_tailer%'"))
        await s.commit()
    _handlers.clear()
    _handlers.update(saved_handlers)
    outbox._async_subs.clear()
    outbox._async_subs.update(saved_subs)
    await db._admin_engine().dispose()
    _clear_engine_caches()


async def _noop(session, event) -> None:
    return None


async def _seed(actor: str, *, label: str = "Hi", entity_id: str = "e1") -> None:
    await insert_business_event(
        kind="test_tailer.happened",
        level="info",
        user_id=actor,
        ip=None,
        org_id=None,
        entity_id=entity_id,
        request_id=None,
        payload={"label": label},
    )


async def _topics() -> list[str]:
    async with db.admin_session_factory()() as s:
        rows = await s.execute(
            text("SELECT topic FROM task_queue WHERE topic LIKE 'evt:test_tailer%' ORDER BY topic")
        )
        return [r[0] for r in rows]


async def _undispatched(kind: str) -> int:
    async with db.admin_session_factory()() as s:
        return await s.scalar(
            text("SELECT count(*) FROM business_events WHERE kind = :k AND dispatched_at IS NULL"),
            {"k": kind},
        )


@pytest.mark.asyncio
async def test_tick_enqueues_one_task_per_subscriber_and_marks_the_fact_dispatched(iso):
    outbox.on_async(_TailEvent, "counter", _noop, as_actor=False)
    outbox.on_async(_TailEvent, "search", _noop, as_actor=False)
    await _seed(str(uuid.uuid4()))

    dispatched = await EventTailer(0).tick()

    assert dispatched == 1
    assert await _topics() == [
        "evt:test_tailer.happened:counter",
        "evt:test_tailer.happened:search",
    ]
    assert await _undispatched("test_tailer.happened") == 0


@pytest.mark.asyncio
async def test_worker_runs_the_consumer_with_the_reconstructed_typed_event(iso):
    seen: list[object] = []

    async def handler(session, event) -> None:
        seen.append(event)

    outbox.on_async(_TailEvent, "counter", handler, as_actor=False)
    actor = str(uuid.uuid4())
    await _seed(actor, label="Ship it", entity_id="e7")

    factory = db.admin_session_factory()
    await EventTailer(0, session_factory=factory).tick()
    worker = TaskWorker(0, session_factory=factory)
    while await worker.tick():
        pass

    assert len(seen) == 1
    event = seen[0]
    assert isinstance(event, _TailEvent)
    assert event.actor_id == actor
    assert event.entity_id == "e7"
    assert event.label == "Ship it"


@pytest.mark.asyncio
async def test_an_unknown_kind_is_marked_dispatched_without_enqueuing(iso):
    async with db.admin_session_factory()() as s:
        await s.execute(
            text(
                "INSERT INTO business_events (kind, level, user_id) "
                "VALUES ('test_tailer.legacy', 'info', NULL)"
            )
        )
        await s.commit()

    assert await EventTailer(0).tick() == 1
    assert await _topics() == []
    assert await _undispatched("test_tailer.legacy") == 0


def test_org_seed_apps_register_durable_consumers_of_organization_created():
    # Importing the composition root mounts every app; each welcome-seed app declares a durable
    # async consumer of OrganizationCreated via the manifest's consumes_when_enabled. Checked by
    # topic string (shared may not import a bounded context to name the event type).
    import apps.main  # noqa: F401

    topics = set(_handlers)
    for app in ("todo", "files", "calendar", "learning", "pages"):
        assert f"evt:organizations.created:{app}_welcome" in topics


@pytest.mark.asyncio
async def test_a_second_tick_does_not_refan_a_dispatched_fact(iso):
    outbox.on_async(_TailEvent, "counter", _noop, as_actor=False)
    await _seed(str(uuid.uuid4()))

    assert await EventTailer(0).tick() == 1
    assert await EventTailer(0).tick() == 0  # nothing left undispatched
    assert await _topics() == ["evt:test_tailer.happened:counter"]  # not duplicated
