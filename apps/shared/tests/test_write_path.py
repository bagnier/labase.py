"""The journal's write path: emit persists on the caller's transaction."""

import uuid
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from apps.shared.events import BusinessEvent, OrgScoped, repository
from apps.shared.events.bus import events
from apps.shared.events.wiring import wiring
from apps.shared.logs import capture
from apps.shared.persistence import database as db


@dataclass(frozen=True, kw_only=True)
class _P1Event(OrgScoped, BusinessEvent):
    app_name = "test_p1"
    verb = "happened"
    label: str | None = None


def _clear_engine_caches() -> None:
    db._user_engine.cache_clear()
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


@pytest_asyncio.fixture
async def _clean_p1():
    # A fresh engine on this test's loop, and our committed facts cleaned up.
    _clear_engine_caches()
    wiring.declare(_P1Event)

    async def _wipe():
        async with db.admin_session_factory()() as s:
            await s.execute(text("DELETE FROM business_events WHERE kind LIKE 'test_p1.%'"))
            await s.commit()

    await _wipe()
    yield
    await _wipe()
    await db._admin_engine().dispose()
    _clear_engine_caches()


async def _count_p1(actor: uuid.UUID) -> int:
    async with db.admin_session_factory()() as s:
        return await s.scalar(
            text("SELECT count(*) FROM business_events WHERE user_id = :a"), {"a": actor}
        )


# ── The fact commits iff the action commits ───────────────────────────────────────────────────


@pytest.mark.usefixtures("_clean_p1")
@pytest.mark.asyncio
async def test_emit_writes_the_record_on_the_given_session():
    actor, eid = uuid.uuid7(), uuid.uuid7()
    async with db.admin_session_factory()() as session:
        await events.emit(
            _P1Event(user_id=actor, org_id=uuid.uuid7(), entity_id=eid, label="Hi"), session
        )
        await session.commit()
    async with db.admin_session_factory()() as session:
        record = (
            await session.execute(
                text("SELECT kind, entity_id, payload FROM business_events WHERE user_id = :a"),
                {"a": actor},
            )
        ).first()
    assert record is not None
    assert record.kind == "test_p1.happened"
    assert record.entity_id == eid
    assert record.payload["label"] == "Hi"
    assert "user_id" not in record.payload  # lifted to its column
    assert "org_id" not in record.payload


@pytest.mark.usefixtures("_clean_p1")
@pytest.mark.asyncio
async def test_the_journal_composes_kind_from_the_two_halves_it_stores():
    """``kind`` is a generated column: no writer can put a kind disagreeing with its halves."""
    actor = uuid.uuid7()
    async with db.admin_session_factory()() as session:
        await session.execute(
            text(
                "INSERT INTO business_events (app_name, verb, user_id) "
                "VALUES ('test_p1', 'happened', :a)"
            ),
            {"a": actor},
        )
        await session.commit()
    async with db.admin_session_factory()() as session:
        kind = await session.scalar(
            text("SELECT kind FROM business_events WHERE user_id = :a"), {"a": actor}
        )
    assert kind == "test_p1.happened"

    async with db.admin_session_factory()() as session:
        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    "INSERT INTO business_events (app_name, verb, kind) "
                    "VALUES ('test_p1', 'happened', 'test_p1.lied')"
                )
            )


@pytest.mark.usefixtures("_clean_p1")
@pytest.mark.asyncio
async def test_emit_rolls_back_with_the_transaction():
    actor = uuid.uuid7()
    async with db.admin_session_factory()() as session:
        await events.emit(_P1Event(user_id=actor, org_id=uuid.uuid7()), session)
        await session.rollback()
    assert await _count_p1(actor) == 0


@pytest.mark.usefixtures("_clean_p1")
@pytest.mark.asyncio
async def test_emit_persists_the_business_event_and_rolls_back_atomically():
    committed, rolled = uuid.uuid7(), uuid.uuid7()
    async with db.admin_session_factory()() as session:
        await events.emit(_P1Event(user_id=committed, org_id=uuid.uuid7()), session=session)
        await session.commit()
    async with db.admin_session_factory()() as session:
        await events.emit(_P1Event(user_id=rolled, org_id=uuid.uuid7()), session=session)
        await session.rollback()
    assert await _count_p1(committed) == 1
    assert await _count_p1(rolled) == 0


@pytest.mark.usefixtures("_clean_p1")
@pytest.mark.asyncio
async def test_the_record_keeps_the_org_name_after_the_org_is_gone():
    actor, org = uuid.uuid7(), uuid.uuid7()
    async with db.admin_session_factory()() as session:
        await session.execute(
            text("INSERT INTO organizations (id, name, handle) VALUES (:i, :n, :h)"),
            {"i": org, "n": "Acme Corp", "h": f"acme-{org.hex[:8]}"},
        )
        await session.commit()
    try:
        async with db.admin_session_factory()() as session:
            await events.emit(_P1Event(user_id=actor, org_id=org, label="Hi"), session)
            await session.commit()
        async with db.admin_session_factory()() as session:
            await session.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": org})
            await session.commit()
        async with db.admin_session_factory()() as session:
            name = await session.scalar(
                text("SELECT org_name FROM business_events WHERE user_id = :a"), {"a": actor}
            )
        assert name == "Acme Corp"
    finally:
        async with db.admin_session_factory()() as session:
            await session.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": org})
            await session.commit()


def test_a_secret_that_slips_past_the_class_check_does_not_open_an_issue(monkeypatch, log_chain):
    """The mask is said as a warning, not an issue: the fact is already recorded once."""
    monkeypatch.setattr(repository, "_is_secret_field_name", lambda name: name == "entity_name")
    capture._QUEUE.clear()

    payload = repository._fact_payload(_P1Event(org_id=uuid.uuid7(), entity_name="acme"))

    lines = [
        (line.level, line.name, "MaskedSecret" in line.payload.get("exception", ""))
        for line in log_chain()
        if line.logger == repository.__name__
    ]
    assert (payload["entity_name"], lines, list(capture._QUEUE)) == (
        "***",
        [("warning", "business_event.secret_field_masked", True)],
        [],
    )
