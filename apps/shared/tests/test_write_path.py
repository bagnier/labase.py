"""Business-events write path — persists transactionally on emit and degrades safely."""

import uuid
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from apps.shared.events import BusinessEvent, OrgScoped
from apps.shared.events.bus import events
from apps.shared.events.registry import registry
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
    # Bypass the ApiDriver's shared test connection (its background loop) with a fresh engine on
    # this test's loop, and clean up our own committed rows — the pattern test_bus established.
    _clear_engine_caches()
    registry.declare_events(_P1Event)  # emit refuses an undeclared event

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


# ── Transactional persist (Phase 1): the fact commits iff the action commits ──────────────────


@pytest.mark.usefixtures("_clean_p1")
@pytest.mark.asyncio
async def test_emit_writes_the_row_on_the_given_session():
    """emit persists the fact on the caller's session — scoping to columns, the rest in payload."""
    actor, eid = uuid.uuid7(), uuid.uuid7()
    async with db.admin_session_factory()() as session:
        await events.emit(
            _P1Event(user_id=actor, org_id=uuid.uuid7(), entity_id=eid, label="Hi"), session
        )
        await session.commit()
    async with db.admin_session_factory()() as session:
        row = (
            await session.execute(
                text("SELECT kind, entity_id, payload FROM business_events WHERE user_id = :a"),
                {"a": actor},
            )
        ).first()
    assert row is not None
    assert row.kind == "test_p1.happened"
    assert row.entity_id == eid
    assert row.payload["label"] == "Hi"
    assert "user_id" not in row.payload  # scoping fields are lifted to their own columns
    assert "org_id" not in row.payload


@pytest.mark.usefixtures("_clean_p1")
@pytest.mark.asyncio
async def test_the_trail_composes_kind_from_the_two_halves_it_stores():
    """``kind`` is a view over the row, not a value in it.

    An event names itself in two parts, and the class composes them; the table now does the same —
    ``kind`` is generated from ``app_name`` and ``verb``. So the two derivations cannot drift: there
    is no second writer to keep in sync, and no writer at all can put a dotted string in that column
    (which is what used to let a hand-written kind disagree with the halves it claimed to be)."""
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
    """A rolled-back transaction leaves no event — atomic with the action (best-effort before)."""
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
async def test_the_row_keeps_the_org_name_after_the_org_is_gone():
    """The trail is history: it has to stay readable once its subjects are deleted.

    Resolving an org's name at read time works only while the org exists — and deleting an org is a
    product feature, so the audit trail would lose the *where* exactly when it matters. The name is
    therefore pinned onto the row as it was then (the same reason ``user_name`` is denormalized:
    RLS can't resolve a co-member's handle later either).
    """
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
