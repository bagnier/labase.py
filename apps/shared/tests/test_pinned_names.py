"""``pinned_names`` pins the email when the account has no handle yet."""

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
    """Only a ``profiles`` row, its FK check deferred to a commit that never comes."""
    uid = str(uuid.uuid4())
    email = f"{uid}@pinned-fallback.example"
    async with acting_as(db_session, uid), db_session.begin_nested() as savepoint:
        await db_session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        await db_session.execute(_INSERT_HANDLELESS_PROFILE, {"u": uid, "e": email})
        names = await EventRepository(db_session).pinned_names(uuid.UUID(uid), None)
        await savepoint.rollback()

    assert names == (email, None)
