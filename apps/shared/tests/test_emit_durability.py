"""Which facts may be detached — the criterion, proved against the real request teardown.

``emit(fact, session)`` rides the request's transaction, and ``_commit_on_success`` commits it on a
clean exit but rolls it back on an exception. So the two failure shapes a handler can take are *not*
equivalent for the journal: returning a 4xx keeps the fact, raising ``HTTPException`` loses
it.

That asymmetry is why the journal holds no refusals. A fact emitted on a raising path would need to
escape its transaction to survive, and the facts that wanted to — a blocked revoke, a denied admin
surface — turned out to describe nothing that happened. They are log lines now, and ``emit`` has no
exception left. This pins the mechanism, so the reasoning stays derivable rather than remembered.
"""

import uuid

import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from apps.shared.events import BusinessEvent
from apps.shared.events.bus import events
from apps.shared.events.wiring import wiring
from apps.shared.persistence import database as db
from apps.shared.persistence.database import AdminSession
from apps.shared.queue import enqueue

_KIND = "test_durability.happened"


class _DurabilityEvent(BusinessEvent):
    app_name = "test_durability"
    verb = "happened"


router = APIRouter()


async def _mutate_and_emit(actor: uuid.UUID, session: AdminSession) -> None:
    """A mutation and its fact on one transaction — the shape every emitting route takes. The row
    is a queued task, the cheapest write the base owns that needs no table of the test's own."""
    await enqueue(session, _KIND, {"actor": str(actor)})
    await events.emit(_DurabilityEvent(user_id=actor), session)


@router.post("/returns-an-error")
async def returns_an_error(actor: uuid.UUID, session: AdminSession) -> JSONResponse:
    await _mutate_and_emit(actor, session)
    return JSONResponse({"detail": "nope"}, status_code=status.HTTP_400_BAD_REQUEST)


@router.post("/raises")
async def raises(actor: uuid.UUID, session: AdminSession) -> JSONResponse:
    await _mutate_and_emit(actor, session)
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="nope")


def _clear_engine_caches() -> None:
    db._user_engine.cache_clear()
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


async def _wipe() -> None:
    async with db.admin_session_factory()() as session:
        await session.execute(text("DELETE FROM business_events WHERE kind = :k"), {"k": _KIND})
        await session.execute(text("DELETE FROM task_queue WHERE topic = :k"), {"k": _KIND})
        await session.commit()


@pytest_asyncio.fixture
async def client():
    # A fresh engine on this test's loop, as the sibling write-path tests do: the ApiDriver's
    # shared connection lives on another loop and would deadlock the commits asserted here.
    _clear_engine_caches()
    wiring.declare(_DurabilityEvent)
    await _wipe()
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await _wipe()
    await db._admin_engine().dispose()
    _clear_engine_caches()


async def _rows_and_facts(actor: uuid.UUID) -> tuple[int, int]:
    """How many of the actor's rows and facts committed — read together, since the claim is that
    one never commits without the other."""
    async with db.admin_session_factory()() as session:
        rows = await session.scalar(
            text("SELECT count(*) FROM task_queue WHERE topic = :k AND payload->>'actor' = :a"),
            {"k": _KIND, "a": str(actor)},
        )
        facts = await session.scalar(
            text("SELECT count(*) FROM business_events WHERE kind = :k AND user_id = :a"),
            {"k": _KIND, "a": actor},
        )
        return rows, facts


@pytest.mark.asyncio
async def test_a_fact_survives_a_handler_that_returns_an_error_response(client):
    actor = uuid.uuid7()

    await client.post("/returns-an-error", params={"actor": str(actor)})

    assert await _rows_and_facts(actor) == (1, 1)


@pytest.mark.asyncio
async def test_a_fact_is_rolled_back_by_a_handler_that_raises(client):
    actor = uuid.uuid7()

    await client.post("/raises", params={"actor": str(actor)})

    assert await _rows_and_facts(actor) == (0, 0)
