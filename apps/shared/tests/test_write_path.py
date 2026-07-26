"""Business-events write path — persists transactionally on emit and degrades safely."""

import uuid
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text

from apps.shared.events import BusinessEvent
from apps.shared.events.bus import events
from apps.shared.events.repository import insert_business_event
from apps.shared.persistence import database as db


@dataclass(frozen=True, kw_only=True)
class _P1Event(BusinessEvent):
    kind = "test_p1.happened"
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


@pytest.mark.asyncio
async def test_failed_write_logs_a_warning_instead_of_raising():
    # Regression: the warning must not pass `event=`/`kind=` under structlog's positional
    # message key, and a lost row must never crash the fire-and-forget write task.
    uid = uuid.uuid7()
    with (
        patch(
            "apps.shared.events.repository.admin_session_factory",
            side_effect=RuntimeError("db down"),
        ),
        patch("apps.shared.events.repository.log") as log,
    ):
        await insert_business_event(
            kind="auth.signed_in",
            level="info",
            user_id=uid,
            ip=None,
            org_id=None,
            request_id=None,
            payload=None,
        )
    log.warning.assert_called_once_with(
        "business_event.write_failed", kind="auth.signed_in", user_id=uid
    )


# ── Transactional persist (Phase 1): the fact commits iff the action commits ──────────────────


@pytest.mark.asyncio
async def test_persist_fact_writes_the_row_on_the_given_session(_clean_p1):
    """emit persists the fact on the caller's session — scoping to columns, the rest in payload."""
    actor, eid = uuid.uuid7(), uuid.uuid7()
    async with db.admin_session_factory()() as session:
        await events._persist_fact(
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


@pytest.mark.asyncio
async def test_persist_fact_rolls_back_with_the_transaction(_clean_p1):
    """A rolled-back transaction leaves no event — atomic with the action (best-effort before)."""
    actor = uuid.uuid7()
    async with db.admin_session_factory()() as session:
        await events._persist_fact(_P1Event(user_id=actor), session)
        await session.rollback()
    assert await _count_p1(actor) == 0


@pytest.mark.asyncio
async def test_persist_fact_without_a_session_is_a_detached_best_effort_write():
    """No ambient session (auth signals) → scheduled off the critical path; emit never awaits it."""
    import asyncio

    with patch.object(events, "_record_detached", new=AsyncMock()) as detached:
        await events._persist_fact(_P1Event(user_id=uuid.uuid7(), label="x"), None)
        detached.assert_not_awaited()  # coroutine scheduled, not yet run
        await asyncio.sleep(0)  # let the created task run
    detached.assert_awaited_once()
    assert detached.await_args is not None
    assert detached.await_args.args[0].kind == "test_p1.happened"


@pytest.mark.asyncio
async def test_emit_persists_the_business_event_and_rolls_back_atomically(_clean_p1):
    from apps.shared.events.bus import events
    from apps.shared.events.registry import registry

    registry.declare_events("test_p1", _P1Event)  # emit refuses an undeclared event
    committed, rolled = uuid.uuid7(), uuid.uuid7()
    async with db.admin_session_factory()() as session:
        await events.emit(_P1Event(user_id=committed), session=session)
        await session.commit()
    async with db.admin_session_factory()() as session:
        await events.emit(_P1Event(user_id=rolled), session=session)
        await session.rollback()
    assert await _count_p1(committed) == 1
    assert await _count_p1(rolled) == 0
