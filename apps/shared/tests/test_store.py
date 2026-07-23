"""Business-events store — the write path degrades safely, and the feed projection is rich."""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text

from apps.shared import clock
from apps.shared.events import BusinessEvent
from apps.shared.events.repository import BusinessEventRow
from apps.shared.events.store import (
    _ago,
    activity_entries,
    insert_business_event,
    persist_fact,
)
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
    # this test's loop, and clean up our own committed rows — the pattern test_outbox established.
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


async def _count_p1(actor: str) -> int:
    async with db.admin_session_factory()() as s:
        return await s.scalar(
            text("SELECT count(*) FROM business_events WHERE user_id = :a"), {"a": uuid.UUID(actor)}
        )


def _row(*, kind="todo.created", level="info", icon="clipboard-text", payload=None, ts=None):
    return BusinessEventRow(
        ts=ts or clock.now(),
        level=level,
        kind=kind,
        icon=icon,
        org_id=None,
        user_id=None,
        entity_id=None,
        request_id=None,
        payload=payload or {},
    )


def test_activity_entries_surface_who_what_which_document():
    """The feed shows the actor, the humanized verb and the object's own name — never the kind."""
    [entry] = activity_entries([_row(payload={"actor": "alice", "label": "Ship the Q3 report"})])
    assert entry["who"] == "alice"
    assert entry["label"] == "Created"  # humanized from the kind, verb only
    assert entry["detail"] == "Ship the Q3 report"  # the "which document"
    assert "todo.created" not in (entry["label"], entry["detail"])  # raw kind never surfaces


def test_activity_entries_drop_the_actor_on_the_users_own_trail():
    """The profile feed is all the viewer's own actions, so repeating 'who' is noise."""
    [entry] = activity_entries([_row(payload={"actor": "alice"})], show_actor=False)
    assert entry["who"] is None


def test_activity_entries_carry_level_for_the_node_colour():
    [entry] = activity_entries([_row(level="warning", kind="auth.password_changed")])
    assert entry["level"] == "warning"


def test_activity_entries_take_an_href_from_the_surface_link():
    """Each surface supplies its own deep link (entity page, filtered logs…) via ``link``."""
    row = _row(kind="pages.created")
    [entry] = activity_entries([row], link=lambda r: f"/go/{r.kind}")
    assert entry["href"] == "/go/pages.created"
    [plain] = activity_entries([row])  # no link → no href, rendered as text
    assert plain["href"] is None


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=5), "just now"),
        (timedelta(minutes=3), "3m ago"),
        (timedelta(hours=4), "4h ago"),
        (timedelta(days=2), "2d ago"),
    ],
)
def test_ago_is_a_compact_relative_moment(delta, expected):
    now = clock.now()
    assert _ago(now - delta, now) == expected


@pytest.mark.asyncio
async def test_failed_write_logs_a_warning_instead_of_raising():
    # Regression: the warning must not pass `event=`/`kind=` under structlog's positional
    # message key, and a lost row must never crash the fire-and-forget write task.
    with (
        patch(
            "apps.shared.events.store.admin_session_factory",
            side_effect=RuntimeError("db down"),
        ),
        patch("apps.shared.events.store.log") as log,
    ):
        await insert_business_event(
            kind="auth.signed_in",
            level="info",
            user_id="not-a-uuid",
            ip=None,
            org_id=None,
            request_id=None,
            payload=None,
        )
    log.warning.assert_called_once_with(
        "business_event.write_failed", kind="auth.signed_in", user_id="not-a-uuid"
    )


# ── Transactional persist (Phase 1): the fact commits iff the action commits ──────────────────


@pytest.mark.asyncio
async def test_persist_fact_writes_the_row_on_the_given_session(_clean_p1):
    """emit persists the fact on the caller's session — scoping to columns, the rest in payload."""
    actor = str(uuid.uuid4())
    async with db.admin_session_factory()() as session:
        await persist_fact(
            _P1Event(actor_id=actor, org_id=str(uuid.uuid4()), entity_id="e1", label="Hi"), session
        )
        await session.commit()
    async with db.admin_session_factory()() as session:
        row = (
            await session.execute(
                text("SELECT kind, entity_id, payload FROM business_events WHERE user_id = :a"),
                {"a": uuid.UUID(actor)},
            )
        ).first()
    assert row is not None
    assert row.kind == "test_p1.happened"
    assert row.entity_id == "e1"
    assert row.payload["label"] == "Hi"
    assert "actor_id" not in row.payload  # scoping fields are lifted to their own columns
    assert "org_id" not in row.payload


@pytest.mark.asyncio
async def test_persist_fact_rolls_back_with_the_transaction(_clean_p1):
    """A rolled-back transaction leaves no event — atomic with the action (best-effort before)."""
    actor = str(uuid.uuid4())
    async with db.admin_session_factory()() as session:
        await persist_fact(_P1Event(actor_id=actor), session)
        await session.rollback()
    assert await _count_p1(actor) == 0


@pytest.mark.asyncio
async def test_persist_fact_without_a_session_is_a_detached_best_effort_write():
    """No ambient session (auth signals) → scheduled off the critical path; emit never awaits it."""
    import asyncio

    with patch("apps.shared.events.store.insert_business_event", new=AsyncMock()) as insert:
        await persist_fact(_P1Event(actor_id=str(uuid.uuid4()), label="x"), None)
        insert.assert_not_awaited()  # coroutine scheduled, not yet run
        await asyncio.sleep(0)  # let the created task run
    insert.assert_awaited_once()
    assert insert.await_args is not None
    assert insert.await_args.kwargs["kind"] == "test_p1.happened"


@pytest.mark.asyncio
async def test_emit_persists_the_business_event_and_rolls_back_atomically(_clean_p1):
    from apps.shared.events.bus import EventBus

    committed, rolled = str(uuid.uuid4()), str(uuid.uuid4())
    async with db.admin_session_factory()() as session:
        await EventBus().emit(_P1Event(actor_id=committed), session=session)
        await session.commit()
    async with db.admin_session_factory()() as session:
        await EventBus().emit(_P1Event(actor_id=rolled), session=session)
        await session.rollback()
    assert await _count_p1(committed) == 1
    assert await _count_p1(rolled) == 0
