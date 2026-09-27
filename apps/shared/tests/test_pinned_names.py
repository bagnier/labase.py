"""Which name a fact pins for its actor when the account never set a handle.

``EventRepository.pinned_names`` resolves the actor's handle at write time to pin it onto the
fact's ``user_name`` column (see ``apps/timeline/tests/test_actor_naming.py``). ``profiles.handle``
is only ever set by visiting ``/profile`` (``ProfileRepository.auto_handle``), so an account that
emits a fact without ever having opened it still has nothing to pin there — ``profiles.email``,
set atomically at signup, is the one column always available instead.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events.repository import EventRepository
from tests.rls import acting_as

_INSERT_HANDLELESS_PROFILE = text(
    "insert into profiles (user_id, email, handle) values (:u, :e, null)"
)


@pytest.mark.asyncio
async def test_pinned_names_falls_back_to_the_email_when_the_handle_is_still_unset(
    db_session: AsyncSession,
):
    """No real GoTrue user needed: the row under test is the ``profiles`` one alone, seeded
    directly with its FK check deferred to a commit this test never makes."""
    uid = str(uuid.uuid4())
    email = f"{uid}@pinned-fallback.example"
    async with acting_as(db_session, uid), db_session.begin_nested() as savepoint:
        await db_session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        await db_session.execute(_INSERT_HANDLELESS_PROFILE, {"u": uid, "e": email})
        names = await EventRepository(db_session).pinned_names(uuid.UUID(uid), None)
        await savepoint.rollback()

    assert names == (email, None)
